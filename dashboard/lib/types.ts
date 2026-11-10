export type Topic = {
 id:string; objective:string; primary_question:string; suggested_probes:string[]; required_information:string[]; optional_information:string[]; clarification_conditions:string[]; deeper_probe_conditions:string[]; max_followups:number; next_node:string|null;
 transitions:{when:'required_covered'|'irrelevant'|'always';target_node:string|null}[];
};
export type Pathway = {title:string;objective:string;nodes:Topic[];max_total_turns:number;completion_rule:'all_topics_visited'|'all_required_covered'};
export type Project = {id:string;name:string};
export type Study = {id:string;title:string;status:string;pathway:Pathway};
export type Interview = {id:string;status:string;created_at:string;updated_at:string;participant_label?:string;node_id?:string;coverage?:unknown};
export type Transcript = {id:string;question:string;answer:string;source:string;created_at:string;decision?:Record<string,unknown>};
export type InterviewDetail = {id:string;status:string;study_id:string;state:unknown;transcript:Transcript[];consent:Record<string,unknown>;messages?:{id:string;status:string;error_code?:string|null}[]};
export type Health = {status:string;mode:string;auth_mode?:string;checks:{database:string;whatsapp_configured:boolean;openai_configured:boolean;commercial_eligibility:string}};
