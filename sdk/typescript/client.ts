/** Typed, authenticated local client for Node.js/desktop integrations. */
export type CommandCheck = {kind:'command'; label:string; argv:string[]; timeout_seconds?:number; criterion_indices?:number[]};
export type FileCheck = {kind:'file_exists'|'file_contains'; label:string; path:string; text?:string; criterion_indices?:number[]};
export type CreatorCheck = {kind:'creator_offer';label:string;path:string;rule:'budget'|'currency'|'deadline'|'source_evidence';argv?:[];criterion_indices:number[]};
export type CompletionCheck = CommandCheck|FileCheck|CreatorCheck;
export interface BuildSpecification {root:string;goal:string;constraints?:string[];acceptance_criteria?:string[];checks:CompletionCheck[];max_turns?:number;max_seconds?:number;approved:true}
export interface CaseEvidence {case_id:string;passed:boolean;reason:string;expected:unknown;actual:unknown;source?:string}
export interface CheckEvidence {label:string;passed:boolean;status?:string;details:string;cases?:CaseEvidence[]}
export interface BuildRecord {id:string;root:string;state:string;spec:BuildSpecification;outcome?:{code:string;title:string;summary:string};payload:{turn:number;message:string;worktree:string|null;checks:CheckEvidence[];criteria?:{text:string;status:string;evidence:string;automated_status?:string}[]}}
export interface BuildEvent {seq:number;kind:string;created_at:string;payload:Record<string,unknown>}
export interface RecordedAttempt {label:string;kind:string;turn:number;elapsed_ms:number|null;worker_ms:number|null;usage:Record<string,number>;checks_passed:number;checks_total:number;cases_passed:number;cases_total:number;checks:CheckEvidence[];output:string|null}
export interface Comparison {mode:string;comparable:boolean;notes:string[];baseline:RecordedAttempt|null;result:RecordedAttempt|null;replay:RecordedAttempt[]}

export class PromptAidClient {
  readonly #base: URL;
  readonly #token: string;
  readonly #fetch: typeof fetch;
  readonly #timeout: number;
  constructor(baseURL:string,token:string,options:{fetch?:typeof fetch;timeoutMs?:number}={}) {
    const base = new URL(baseURL);
    if (base.protocol !== 'http:' || base.hostname !== '127.0.0.1' || base.username || base.password || base.search || base.hash || base.pathname !== '/') {
      throw new Error('Use the configured http://127.0.0.1:port local service URL.');
    }
    if (!token || token.length<32 || token.length>8192 || /[\r\n]/.test(token)) throw new Error('A private service token is required.');
    this.#base=base;this.#token=token;this.#fetch=options.fetch ?? fetch;this.#timeout=options.timeoutMs ?? 10000;
  }
  async #request<T>(path:string,method='GET',body?:unknown):Promise<T> {
    const response=await this.#fetch(new URL(path,this.#base),{method,redirect:'error',signal:AbortSignal.timeout(this.#timeout),
      headers:{Authorization:`Bearer ${this.#token}`,...(body === undefined ? {} : {'Content-Type':'application/json'})},
      ...(body === undefined ? {} : {body:JSON.stringify(body)})});
    if (!response.ok) throw new Error(`Prompt Aid request failed (${response.status}).`);
    if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Expected a JSON response.');
    const reader=response.body?.getReader(); if (!reader) throw new Error('Empty service response.');
    const decoder=new TextDecoder();let text='',size=0;
    try {
      while (true) {const {done,value}=await reader.read();if(done)break;size+=value.byteLength;
        if(size>256000){await reader.cancel();throw new Error('Service response exceeds the client limit.');}
        text+=decoder.decode(value,{stream:true});}
      text+=decoder.decode();return JSON.parse(text) as T;
    } finally {reader.releaseLock();}
  }
  #id(id:string):string {if(!/^[a-zA-Z0-9-]{1,80}$/.test(id))throw new Error('Invalid build ID.');return id;}
  listBuilds():Promise<{builds:BuildRecord[]}> {return this.#request('/builds');}
  getBuild(id:string):Promise<BuildRecord> {return this.#request(`/builds/${this.#id(id)}`);}
  startBuild(spec:BuildSpecification):Promise<BuildRecord> {
    if(spec.approved !== true)throw new Error('Explicit approval is required.');
    return this.#request('/builds','POST',spec);
  }
  events(id:string,after=0):Promise<{events:BuildEvent[]}> {
    if(!Number.isSafeInteger(after)||after<0)throw new Error('Invalid event cursor.');
    return this.#request(`/builds/${this.#id(id)}/events?after=${after}`);
  }
  comparison(id:string,baselineID?:string):Promise<Comparison> {
    return this.#request(`/builds/${this.#id(id)}/comparison${baselineID ? '?baseline_id='+this.#id(baselineID) : ''}`);
  }
  stop(id:string):Promise<BuildRecord> {return this.#request(`/builds/${this.#id(id)}/stop`,'POST',{});}
  recheck(id:string,approval:{approved:true;max_seconds?:number}):Promise<BuildRecord> {
    if(approval.approved !== true)throw new Error('Explicit approval is required.');
    return this.#request(`/builds/${this.#id(id)}/recheck`,'POST',approval);
  }
}
