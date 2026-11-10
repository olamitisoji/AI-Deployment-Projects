import hashlib
import hmac
import json
import time
from dataclasses import asdict
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from echo.config import Settings
from echo.database import InboundEvent, Participant, Outbox, Project, Membership, Invitation, Study
from echo.api import create_app

@pytest.fixture
def setup(tmp_path):
    settings=Settings(_env_file=None,encryption_key=Fernet.generate_key().decode(),researcher_token='x'*40,
        database_url=f'sqlite:///{tmp_path}/echo.db',whatsapp_verify_token='verify-test',whatsapp_app_secret='secret-test',
        whatsapp_phone_number_id='123',whatsapp_display_number='15555550100',whatsapp_api_version='v99.0',
        whatsapp_access_token='not-a-live-token',test_recipient_allowlist='15555550101')
    app=create_app(settings,initialize_schema=True)
    with TestClient(app) as client:
        yield client,app,{'Authorization':'Bearer '+'x'*40}

def webhook(client,text='START abc',mid='wamid.1',phone='123',sender='15555550101',timestamp=None):
    data={'object':'whatsapp_business_account','entry':[{'changes':[{'field':'messages','value':{'metadata':{'phone_number_id':phone},'messages':[{'id':mid,'from':sender,'timestamp':str(timestamp or int(time.time())),'type':'text','text':{'body':text}}]}}]}]}
    body=json.dumps(data).encode()
    signature='sha256='+hmac.new(b'secret-test',body,hashlib.sha256).hexdigest()
    return client.post('/webhooks/whatsapp',content=body,headers={'x-hub-signature-256':signature,'content-type':'application/json'})

def study(client,headers):
    p=client.post('/projects',json={'name':'Healthcare research'},headers=headers)
    assert p.status_code==201
    s=client.post(f"/projects/{p.json()['id']}/studies",json={'title':'Admin discovery','objective':'Understand administrative reliability problems','questions':['What workflow takes the most time?']},headers=headers)
    assert s.status_code==201
    return p.json(),s.json()

def test_private_projects_and_health_do_not_expose_secrets(setup):
    c,a,h=setup
    assert c.get('/projects').status_code==401
    assert c.get('/projects',headers={'Authorization':'Bearer wrong'}).status_code==401
    body=c.get('/health').json()
    assert body['checks']['commercial_eligibility']=='unverified'
    assert 'secret-test' not in json.dumps(body)
    assert c.get('/projects',headers=h).json()==[]

def test_create_review_approve_invite_with_secure_reference(setup):
    c,a,h=setup
    p,s=study(c,h)
    assert s['status']=='draft'
    path=f"/studies/{s['id']}"
    assert c.post(path+'/invitations',json={},headers=h).status_code==409
    assert c.post(path+'/approve',headers=h).json()['status']=='approved'
    assert c.put(path+'/pathway',json={'pathway':s['pathway']},headers=h).status_code==409
    invite=c.post(path+'/invitations',json={'kind':'personalized','max_uses':1,'expires_in_days':7},headers=h)
    assert invite.status_code==201
    assert invite.json()['url'].startswith('https://wa.me/15555550100?text=START%20')
    with a.state.sessions() as db:
        row=db.get(Invitation,invite.json()['id'])
        assert row.token_hash==hashlib.sha256(invite.json()['token'].encode()).hexdigest()
        assert invite.json()['token'] not in row.token_hash
    assert c.get(f"/projects/{p['id']}/studies",headers=h).json()[0]['id']==s['id']

def test_cross_project_access_is_hidden(setup):
    c,a,h=setup
    with a.state.sessions() as db:
        p=Project(name='Private other researcher'); db.add(p);db.flush()
        db.add(Membership(project_id=p.id,user_id='someone-else'));db.commit();pid=p.id
    assert c.get(f'/projects/{pid}/studies',headers=h).status_code==404
    assert c.post(f'/projects/{pid}/studies',json={'title':'No','objective':'No','questions':['No?']},headers=h).status_code==404

def test_webhook_verification_signature_scope_and_duplicates(setup):
    c,a,h=setup
    assert c.get('/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=verify-test&hub.challenge=42').text=='42'
    assert c.get('/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=42').status_code==403
    assert c.post('/webhooks/whatsapp',json={}).status_code==403
    assert webhook(c).status_code==200
    assert webhook(c).status_code==200
    assert webhook(c,mid='wrong-id',phone='999').status_code==200
    assert webhook(c,mid='not-allowed',sender='15555559999').status_code==200
    assert webhook(c,mid='future',timestamp=int(time.time())+10000).status_code==200
    with a.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(InboundEvent))==1
        p=db.scalar(select(Participant))
        assert p.phone_cipher!='15555550101'
        assert 'START abc' not in db.get(InboundEvent,'wamid.1').payload_cipher

def test_stop_suppresses_pending_reply_before_worker(setup):
    c,a,h=setup
    webhook(c)
    with a.state.sessions() as db:
        p=db.scalar(select(Participant))
        db.add(Outbox(event_id='old',participant_id=p.id,text_cipher=a.state.vault.seal('Question'),expires_at=int(time.time())+500));db.commit()
    webhook(c,'STOP.','wamid.stop')
    with a.state.sessions() as db:
        assert db.scalar(select(Participant)).opted_out is True
        assert db.scalar(select(Outbox)).status=='suppressed'

def test_large_webhook_rejected_before_json(setup):
    c,a,h=setup
    assert c.post('/webhooks/whatsapp',content=b'x'*(1024*1024+1)).status_code==413

def test_study_questions_are_bounded_and_no_fake_ai_fallback(setup):
    c,a,h=setup
    p,s=study(c,h)
    assert c.post(f"/projects/{p['id']}/studies",json={'title':'x','objective':'x','questions':[]},headers=h).status_code==422
    result=c.post(f"/studies/{s['id']}/propose-pathway",json={'objective':'x','questions':['What?']},headers=h)
    assert result.status_code==503
    assert result.json()['detail']['code']=='credentials_unavailable'
