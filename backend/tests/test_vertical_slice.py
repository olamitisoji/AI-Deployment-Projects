"""Real app/DB/worker integration with only Meta and AI replaced by test doubles.

This is explicitly not evidence of live WhatsApp delivery or speech accuracy.
"""
import hashlib
import hmac
import json
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_api import setup, webhook, study
from echo.api import create_app
from echo.conversation_pathway_engine import Analysis
from echo.database import Interview, Turn, InboundEvent, Participant, Outbox
from echo.worker import run_once

class TestProviders:
    __test__=False
    def __init__(self):self.sent=[];self.downloads=0;self.transcriptions=0;self.analyses=0
    async def send_text(self,to,text,last_inbound_at,now=None):
        self.sent.append(text);return f'outbound.{len(self.sent)}'
    async def download_audio(self,media_id):
        assert media_id=='media1';self.downloads+=1;return b'test-boundary-audio','audio/ogg'
    async def transcribe(self,audio,mime,**kwargs):
        self.transcriptions+=1;return 'The handoff takes time.'
    async def analyze(self,pathway,state,answer,history):
        self.analyses+=1
        if self.analyses==1:
            return Analysis(relevant=True,suggested_action='PROBE_DEEPER',followup='Can you describe what happens during that handoff?')
        criterion=pathway.nodes[0].required_information[0]
        return Analysis(relevant=True,suggested_action='MOVE_TO_NEXT_TOPIC',covered_information=[criterion],evidence=[{'criterion':criterion,'quote':answer}])

def voice(client,mid):
    payload={'object':'whatsapp_business_account','entry':[{'changes':[{'field':'messages','value':{'metadata':{'phone_number_id':'123'},'messages':[{'id':mid,'from':'15555550101','timestamp':str(int(time.time())),'type':'audio','audio':{'id':'media1','mime_type':'audio/ogg; codecs=opus'}}]}}]}]}
    body=json.dumps(payload).encode()
    signature='sha256='+hmac.new(b'secret-test',body,hashlib.sha256).hexdigest()
    assert client.post('/webhooks/whatsapp',content=body,headers={'x-hub-signature-256':signature}).status_code==200

@pytest.mark.asyncio
async def test_signed_invite_consent_voice_followup_completion_durable_export(setup):
    c,app,h=setup
    providers=TestProviders()
    async def tick():
        await run_once(app.state.settings,app.state.sessions,app.state.vault,providers,providers)
    p,s=study(c,h)
    c.post(f"/studies/{s['id']}/approve",headers=h)
    invite=c.post(f"/studies/{s['id']}/invitations",json={},headers=h).json()
    webhook(c,'START '+invite['token'],'start');await tick()
    assert 'AI-assisted' in providers.sent[-1] and 'I CONSENT' in providers.sent[-1]
    voice(c,'preconsent');await tick()
    assert providers.downloads==providers.transcriptions==0
    webhook(c,'I CONSENT','consent');await tick()
    assert providers.sent[-1]=='What workflow takes the most time?'
    voice(c,'voice');await tick()
    assert providers.sent[-1]=='Can you describe what happens during that handoff?'
    assert providers.downloads==providers.transcriptions==providers.analyses==1
    voice(c,'voice');await tick()
    assert providers.transcriptions==1
    webhook(c,'PAUSE','pause');await tick()
    webhook(c,'Another answer while paused','paused-answer');await tick()
    assert providers.analyses==1
    webhook(c,'RESUME','resume');await tick()
    assert providers.sent[-1]=='Can you describe what happens during that handoff?'
    webhook(c,'A missing referral causes an hour of manual checking.','answer2');await tick()
    assert 'complete' in providers.sent[-1]
    interviews=c.get(f"/studies/{s['id']}/interviews",headers=h).json()
    assert len(interviews)==1 and interviews[0]['status']=='completed'
    interview_id=interviews[0]['id']
    # Independent app instance, new DB connections: memory is not the source of truth.
    with TestClient(create_app(app.state.settings)) as restarted:
        detail=restarted.get(f'/interviews/{interview_id}/export',headers=h).json()
        assert detail['consent']['participation'] is True
        assert [turn['source'] for turn in detail['transcript']]==['audio','text']
        assert detail['transcript'][0]['answer']=='The handoff takes time.'
        assert detail['transcript'][0]['decision']['action']=='PROBE_DEEPER'
        assert detail['transcript'][1]['decision']['action']=='COMPLETE_INTERVIEW'
        assert restarted.get(f'/interviews/{interview_id}').status_code==401
    webhook(c,'WITHDRAW','withdraw');await tick()
    result=c.get(f'/interviews/{interview_id}',headers=h).json()
    assert result['status']=='withdrawn' and result['transcript']==[] and result['state']=={}
    with app.state.sessions() as db:
        assert list(db.scalars(select(Turn)))==[]
        assert all(app.state.vault.open(e.payload_cipher)=={} for e in db.scalars(select(InboundEvent)))
    sent=len(providers.sent)
    voice(c,'after-withdraw');await tick()
    assert len(providers.sent)==sent and providers.transcriptions==1
