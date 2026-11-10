"""Researcher API and the signed Meta webhook. Long-running work stays in the worker."""
import json
import hashlib
import re
import secrets
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, JSONResponse
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select, text, update, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .audio_transcription import AIClient, AIError
from .config import Settings, get_settings
from .conversation_pathway_engine import StudyPathway, PathwayNode
from .database import Base, Project, Membership, Study, Invitation, Participant, Interview, InboundEvent, Turn, Outbox, DeliveryEvent, database, now_ts
from .research_synthesis import synthesize_transcripts
from .interview_service import normalize_command
from .security import ResearcherAuth, Vault, token_hash
from .whatsapp_gateway import verify_signature, parse_messages, parse_statuses

BoundedQuestion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
class NewProject(BaseModel):
    name: str = Field(min_length=1, max_length=120)
class GuideInput(BaseModel):
    objective: str = Field(min_length=1, max_length=2000)
    questions: list[BoundedQuestion] = Field(min_length=1, max_length=12)
class NewStudy(GuideInput):
    title: str = Field(min_length=1, max_length=120)
class PathwayInput(BaseModel):
    pathway: StudyPathway
class NewInvitation(BaseModel):
    kind: Literal['general','personalized'] = 'general'
    max_uses: int = Field(default=100, ge=1, le=1000)
    expires_in_days: int = Field(default=7, ge=1, le=30)

def iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat() if timestamp else None

def create_app(settings: Settings | None = None, *, initialize_schema=False):
    settings=settings or get_settings()
    engine,sessions=database(settings.database_url)
    vault=Vault(settings.encryption_key.get_secret_value())
    auth=ResearcherAuth(settings)
    ai=AIClient(settings.openai_api_key.get_secret_value(),settings.transcription_model,settings.decision_model)

    @asynccontextmanager
    async def lifespan(app):
        if initialize_schema:
            Base.metadata.create_all(engine)
        yield
        engine.dispose()

    app=FastAPI(title='Echo researcher API',version='0.1.0',lifespan=lifespan,
        docs_url='/docs' if settings.mode=='local' else None,redoc_url=None)
    app.state.sessions=sessions
    app.state.vault=vault
    app.state.settings=settings
    app.state.ai=ai
    app.state.engine=engine

    @app.middleware('http')
    async def privacy_headers(request,call_next):
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        return response

    def project_access(db,project_id,user):
        project=db.get(Project,project_id)
        if not project or not db.get(Membership,(project_id,user)):
            raise HTTPException(404,'Project not found')
        return project

    def study_access(db,study_id,user):
        study=db.get(Study,study_id)
        if not study: raise HTTPException(404,'Study not found')
        project_access(db,study.project_id,user)
        return study

    def interview_access(db,interview_id,user):
        interview=db.get(Interview,interview_id)
        if not interview: raise HTTPException(404,'Interview not found')
        study_access(db,interview.study_id,user)
        return interview

    def study_json(study):
        return {'id':study.id,'title':study.title,'pathway':vault.open(study.pathway),'status':study.status,'version':study.version}

    def detail_json(db,interview):
        transcript=[]
        for turn in db.scalars(select(Turn).where(Turn.interview_id==interview.id).order_by(Turn.sequence,Turn.created_at,Turn.id)):
            payload=vault.open(turn.payload_cipher)
            transcript.append({**payload,'id':turn.id,'created_at':iso(turn.created_at)})
        return {'id':interview.id,'study_id':interview.study_id,'status':interview.status,
            'created_at':iso(interview.created_at),'updated_at':iso(interview.updated_at),
            'state':vault.open(interview.state_cipher) if interview.state_cipher else {},
            'consent':vault.open(interview.consent_cipher) if interview.consent_cipher else {'status':'deleted'},
            'transcript':transcript,
            'messages':[{'id':row.id,'status':row.status,'error_code':row.error_code} for row in db.scalars(select(Outbox).where(Outbox.interview_id==interview.id).order_by(Outbox.created_at))]}

    @app.get('/health')
    def health():
        try:
            with sessions() as db:
                db.execute(text('SELECT 1'))
            db_status='connected'
        except SQLAlchemyError:
            db_status='unavailable'
        return {'status':'ok' if db_status=='connected' else 'degraded','mode':settings.mode,'auth_mode':settings.auth_mode,
            'checks':{'database':db_status,'whatsapp_configured':settings.whatsapp_configured,
                'openai_configured':bool(settings.openai_api_key.get_secret_value()),
                'commercial_eligibility':'operator_verified' if settings.commercial_eligibility_verified else 'unverified'}}

    @app.get('/projects')
    def list_projects(user=Depends(auth)):
        with sessions() as db:
            return [{'id':p.id,'name':p.name} for p in db.scalars(select(Project).join(Membership).where(Membership.user_id==user).order_by(Project.name))]

    @app.post('/projects',status_code=201)
    def create_project(body:NewProject,user=Depends(auth)):
        with sessions.begin() as db:
            project=Project(name=body.name.strip());db.add(project);db.flush()
            db.add(Membership(project_id=project.id,user_id=user))
            return {'id':project.id,'name':project.name}

    @app.get('/projects/{project_id}/studies')
    def list_studies(project_id:str,user=Depends(auth)):
        with sessions() as db:
            project_access(db,project_id,user)
            return [study_json(s) for s in db.scalars(select(Study).where(Study.project_id==project_id).order_by(Study.title))]

    @app.post('/projects/{project_id}/studies',status_code=201)
    def create_study(project_id:str,body:NewStudy,user=Depends(auth)):
        # This editable starter is explicitly deterministic; AI generation is a separate action.
        pathway=StudyPathway(title=body.title,objective=body.objective,nodes=[PathwayNode(
            id=f'topic_{i+1}',objective=body.objective,primary_question=q,
            suggested_probes=['Can you describe a specific example?','What happened next?'],
            required_information=['A concrete experience relevant to this question'],optional_information=[],
            clarification_conditions=['The response is ambiguous or unrelated to the question'],
            deeper_probe_conditions=['The response lacks a concrete example or its impact'],max_followups=2)
            for i,q in enumerate(body.questions)])
        with sessions.begin() as db:
            project_access(db,project_id,user)
            study=Study(project_id=project_id,title=body.title,pathway=vault.seal(pathway.model_dump()),status='draft')
            db.add(study);db.flush()
            return study_json(study)

    @app.put('/studies/{study_id}/pathway')
    def edit_pathway(study_id:str,body:PathwayInput,user=Depends(auth)):
        with sessions.begin() as db:
            study=study_access(db,study_id,user)
            if study.status!='draft': raise HTTPException(409,'Approved studies are immutable; create a new draft for changes')
            study.pathway=vault.seal(body.pathway.model_dump());study.title=body.pathway.title[:120];study.version+=1
            return study_json(study)

    @app.post('/studies/{study_id}/propose-pathway')
    async def propose(study_id:str,body:GuideInput,user=Depends(auth)):
        with sessions() as db:
            study=study_access(db,study_id,user)
            if study.status!='draft': raise HTTPException(409,'Only draft pathways can receive proposals')
            version=study.version
        try:
            pathway=await app.state.ai.propose_pathway(body.objective,body.questions)
        except AIError as error:
            raise HTTPException(503,{'code':error.code,'message':'AI proposal unavailable. Your editable draft is still saved.'}) from None
        with sessions.begin() as db:
            study=study_access(db,study_id,user)
            if study.status!='draft' or study.version!=version: raise HTTPException(409,'The study changed while the proposal was generated. Try again.')
            study.pathway=vault.seal(pathway.model_dump());study.version+=1
            return study_json(study)

    @app.post('/studies/{study_id}/approve')
    def approve(study_id:str,user=Depends(auth)):
        with sessions.begin() as db:
            study=study_access(db,study_id,user)
            StudyPathway.model_validate(vault.open(study.pathway))
            study.status='approved';study.approved_at=now_ts()
            return study_json(study)

    @app.post('/studies/{study_id}/invitations',status_code=201)
    def invite(study_id:str,body:NewInvitation,user=Depends(auth)):
        with sessions.begin() as db:
            study=study_access(db,study_id,user)
            if study.status!='approved':raise HTTPException(409,'Review and approve the pathway first')
            if not settings.whatsapp_configured or not re.fullmatch(r'[1-9][0-9]{7,14}',settings.whatsapp_display_number):
                raise HTTPException(503,'Configure the official Meta test number before creating a WhatsApp invitation')
            if settings.whatsapp_test_mode and not settings.test_recipients:
                raise HTTPException(503,'Add your approved Meta test recipient before inviting testers')
            token=secrets.token_urlsafe(32)
            invitation=Invitation(study_id=study_id,token_hash=token_hash(token),kind=body.kind,
                max_uses=1 if body.kind=='personalized' else body.max_uses,expires_at=now_ts()+body.expires_in_days*86400)
            db.add(invitation);db.flush()
            return {'id':invitation.id,'token':token,'url':f'https://wa.me/{settings.whatsapp_display_number}?text='+quote('START '+token,safe=''),
                'expires_at':iso(invitation.expires_at),'test_mode':settings.whatsapp_test_mode}

    @app.get('/studies/{study_id}/interviews')
    def list_interviews(study_id:str,user=Depends(auth)):
        with sessions() as db:
            study_access(db,study_id,user)
            result=[]
            for i in db.scalars(select(Interview).where(Interview.study_id==study_id).order_by(Interview.created_at)):
                state=vault.open(i.state_cipher) if i.state_cipher else {}
                result.append({'id':i.id,'status':i.status,'created_at':iso(i.created_at),'updated_at':iso(i.updated_at),
                    'participant_label':'Participant '+i.id[:8],'node_id':state.get('current_node'),'coverage':state.get('coverage',{})})
            return result

    @app.get('/interviews/{interview_id}')
    def interview(interview_id:str,user=Depends(auth)):
        with sessions() as db:return detail_json(db,interview_access(db,interview_id,user))

    @app.get('/interviews/{interview_id}/export')
    def export(interview_id:str,user=Depends(auth)):
        with sessions() as db:
            data=detail_json(db,interview_access(db,interview_id,user))
        return JSONResponse(data,headers={'Content-Disposition':f'attachment; filename="echo-{data["id"]}.json"'})

    @app.get('/studies/{study_id}/synthesis')
    def synthesis(study_id:str,user=Depends(auth)):
        with sessions() as db:
            study_access(db,study_id,user)
            transcripts=[]
            for interview in db.scalars(select(Interview).where(Interview.study_id==study_id,Interview.status.not_in(['withdrawn','expired']))):
                detail=detail_json(db,interview)
                answers=[t.get('answer','') for t in detail['transcript'] if t.get('source') in {'text','audio'}]
                transcripts.append({'id':interview.id,'text':'\n\n'.join(answers)})
            return synthesize_transcripts(transcripts)

    @app.get('/webhooks/whatsapp',response_class=PlainTextResponse)
    def verify_webhook(request:Request):
        params=request.query_params
        expected=settings.whatsapp_verify_token.get_secret_value()
        if params.get('hub.mode')!='subscribe' or not expected or not secrets.compare_digest(params.get('hub.verify_token',''),expected):
            raise HTTPException(403,'Webhook verification failed')
        challenge=params.get('hub.challenge','')
        if not re.fullmatch(r'[0-9]{1,256}',challenge):raise HTTPException(400,'Invalid challenge')
        return challenge

    @app.post('/webhooks/whatsapp')
    async def receive_webhook(request:Request):
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>1024*1024:raise HTTPException(413,'Webhook too large')
        if not verify_signature(bytes(raw),request.headers.get('x-hub-signature-256'),settings.whatsapp_app_secret.get_secret_value()):
            raise HTTPException(403,'Invalid webhook signature')
        try:payload=json.loads(raw)
        except (ValueError,UnicodeDecodeError):raise HTTPException(400,'Invalid webhook JSON') from None
        timestamp=now_ts()
        messages=parse_messages(payload,settings.whatsapp_phone_number_id)
        if len(messages)>100:raise HTTPException(413,'Too many webhook messages')
        for message in messages:
            if not re.fullmatch(r'[1-9][0-9]{7,14}',message.wa_id) or len(message.id)>255:continue
            if not timestamp-settings.retention_days*86400<=message.timestamp<=timestamp:continue
            if message.text and len(message.text)>16000:continue
            if settings.whatsapp_test_mode and message.wa_id not in settings.test_recipients:continue
            try:
                with sessions.begin() as db:
                    if db.get(InboundEvent,message.id):continue
                    participant=db.scalar(select(Participant).where(Participant.phone_hash==vault.phone_hash(message.wa_id)))
                    if not participant:
                        participant=Participant(phone_hash=vault.phone_hash(message.wa_id),phone_cipher=vault.seal(message.wa_id))
                        db.add(participant);db.flush()
                    elif not participant.phone_cipher:
                        participant.phone_cipher=vault.seal(message.wa_id)
                    participant.last_inbound_at=max(participant.last_inbound_at or 0,message.timestamp)
                    command=normalize_command(message.text or '')
                    if command in {'STOP','WITHDRAW','DECLINE'}:
                        participant.opted_out=True
                        db.execute(update(Outbox).where(Outbox.participant_id==participant.id,Outbox.status=='pending').values(status='suppressed',error_code='participant_opted_out'))
                    db.add(InboundEvent(id=message.id,participant_id=participant.id,payload_cipher=vault.seal(asdict(message)),expires_at=timestamp+settings.retention_days*86400))
            except IntegrityError:
                # Concurrent delivery: existing event is sufficient; retry a newly-created sender race.
                with sessions() as db:
                    if not db.get(InboundEvent,message.id):raise HTTPException(503,'Retry webhook delivery') from None
        for status in parse_statuses(payload,settings.whatsapp_phone_number_id):
            if not timestamp-settings.retention_days*86400<=status.timestamp<=timestamp or status.status not in {'sent','delivered','read','failed'} or len(status.id)>255:continue
            key=hashlib.sha256(json.dumps([status.id,status.status,status.timestamp],separators=(',',':')).encode()).hexdigest()
            try:
                with sessions.begin() as db:
                    if db.get(DeliveryEvent,key):continue
                    # Persist even when the send response has not yet supplied
                    # its provider ID. The worker reconciles after saving it.
                    db.add(DeliveryEvent(id=key,provider_id=status.id,status=status.status,timestamp=status.timestamp,
                        error_code=status.error_code,expires_at=timestamp+settings.retention_days*86400))
            except IntegrityError:
                with sessions() as db:
                    if not db.get(DeliveryEvent,key):raise HTTPException(503,'Retry webhook delivery') from None
        return {'received':True}

    return app

def app_factory():
    """Use uvicorn echo.api:app_factory --factory after echo.manage init-db."""
    return create_app()
