"""Explicit approval and bounded, project-scoped Build-mode routes."""
from typing import Annotated,Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
class Input(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)

Text=Annotated[str,Field(min_length=1,max_length=1000)]
Argument=Annotated[str,Field(max_length=1000)]
class Check(Input):
    kind:Literal['command','file_exists','file_contains']
    label:str=Field(min_length=1,max_length=100)
    argv:list[Argument]=Field(default_factory=list,max_length=24)
    path:str|None=Field(default=None,min_length=1,max_length=1024)
    text:str|None=Field(default=None,min_length=1,max_length=2000)
    timeout_seconds:int=Field(default=30,ge=1,le=120)
    @model_validator(mode='after')
    def valid_check(self):
        if self.kind=='command':
            if not self.argv or not self.argv[0].strip() or any('\0' in a for a in self.argv) or self.path is not None or self.text is not None:raise ValueError('Command checks need argv only.')
        else:
            if not self.path or self.argv:raise ValueError('File checks need a relative path.')
            # Validate lexical traversal without reading user files.
            from pathlib import PurePath
            if PurePath(self.path).is_absolute() or '..' in PurePath(self.path).parts:raise ValueError('File check path must stay inside the worktree.')
            if self.kind=='file_contains' and self.text is None:raise ValueError('Provide the required literal text.')
            if self.kind=='file_exists' and self.text is not None:raise ValueError('File existence check does not take text.')
        return self
class StartBuild(Input):
    root:str=Field(min_length=1,max_length=4096)
    goal:str=Field(min_length=1,max_length=12000)
    constraints:list[Text]=Field(default_factory=list,max_length=20)
    acceptance_criteria:list[Text]=Field(default_factory=list,max_length=12)
    checks:list[Check]=Field(min_length=1,max_length=8)
    max_turns:int=Field(default=3,ge=1,le=5)
    max_seconds:int=Field(default=600,ge=10,le=1800)
    approved:bool
    @model_validator(mode='after')
    def approval(self):
        if self.approved is not True or not self.goal.strip():raise ValueError('Approve a nonempty goal before starting.')
        return self

class ResumeBuild(Input):
    answer:str=Field(min_length=1,max_length=4000)
    max_seconds:int=Field(default=600,ge=10,le=1800)
    approved:bool
    @model_validator(mode='after')
    def approval(self):
        if self.approved is not True or not self.answer.strip():raise ValueError('Approve a nonempty clarification.')
        return self

class RecheckBuild(Input):
    approved:bool
    max_seconds:int=Field(default=180,ge=10,le=600)
    @model_validator(mode='after')
    def approval(self):
        if self.approved is not True:raise ValueError('Approve rerunning the existing checks.')
        return self

class ConfirmCriterion(Input):
    approved:bool
    evidence:str=Field(min_length=1,max_length=2000)
    @model_validator(mode='after')
    def approval(self):
        if self.approved is not True or not self.evidence.strip():raise ValueError('Confirm the behavior and describe what you checked.')
        return self

def register(app,controller):
    @app.get('/builds/config')
    def config():return controller.config()
    @app.get('/builds/suggestions')
    def suggestions(root:str):
        from backend.check_suggestions import suggest_checks
        from backend.builds import git
        root=controller.store.workspace.root(root)
        result=suggest_checks(root)
        repository=git(root,'rev-parse','--show-toplevel',check=False)
        ready=repository.returncode==0 and repository.stdout.strip()==root
        if ready:
            ready=git(root,'rev-parse','--verify','HEAD',check=False).returncode==0 and not git(root,'status','--porcelain').stdout.strip()
        return {'root':root,**result,'environment_memory':controller.store.environment(root),'ready':ready,'readiness_message':
            'Your project is ready. Changes will be made in a separate worktree.' if ready else
            'Save a clean Git checkpoint before starting: commit or stash your changes. Prompt Aid will leave your original files untouched.'}
    @app.get('/builds')
    def builds():return {'builds':controller.store.list()}
    @app.post('/builds')
    def start(body:StartBuild):return controller.start(body.model_dump())
    @app.get('/builds/{id}')
    def build(id:str):return controller.store.get(id)
    @app.post('/builds/{id}/resume')
    def resume(id:str,body:ResumeBuild):return controller.resume(id,body.answer,body.max_seconds)
    @app.post('/builds/{id}/recheck')
    def recheck(id:str,body:RecheckBuild):return controller.recheck(id,body.max_seconds)
    @app.post('/builds/{id}/criteria/{index}/confirm')
    def confirm(id:str,index:int,body:ConfirmCriterion):return controller.attest(id,index,body.evidence)
    @app.get('/builds/{id}/events')
    def events(id:str,after:int=0):return {'events':controller.store.events(id,max(0,after))}
    @app.get('/builds/{id}/diff')
    def diff(id:str):return {'diff':controller.diff(id)}
    @app.post('/builds/{id}/stop')
    def stop(id:str):return controller.stop(id)
