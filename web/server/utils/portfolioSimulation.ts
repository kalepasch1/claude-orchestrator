export const SIM_OPTIONS = {
  archetype: ['saas','marketplace','consumer','services','fintech','legaltech','healthtech','infrastructure','media','other'], stage: ['idea','prototype','pre_revenue','early_revenue','growth','mature'], team_size: ['solo','2_5','6_20','21_plus'], ai_spend: ['under_250','250_1000','1000_5000','5000_plus'], objectives: ['ship_faster','reduce_cost','grow_revenue','improve_quality','reduce_risk','automate_operations','expand_distribution','strengthen_security'], capabilities: ['identity','billing','analytics','design_system','legal_ops','customer_support','growth','data_pipeline','ai_routing','security','deployment','research'], tools: ['openai','anthropic','google_ai','local_models','vercel','supabase','github','figma','stripe','other'], constraints: ['privacy_first','regulated','low_budget','small_team','high_availability','data_residency','no_vendor_lockin'],
} as const
type MultiKey='objectives'|'capabilities'|'tools'|'constraints'
interface Venture { archetype:string;stage:string;team_size:string;ai_spend:string;objectives:string[];capabilities:string[];tools:string[];constraints:string[] }
const sets:Record<string,Set<string>>=Object.fromEntries(Object.entries(SIM_OPTIONS).map(([k,v])=>[k,new Set<string>(v)]))
const spend:Record<string,number>={under_250:125,'250_1000':625,'1000_5000':3000,'5000_plus':9000}
const label=(v:string)=>v.replaceAll('_',' ')
const list=(v:any,k:string):string[]=>[...new Set<string>((Array.isArray(v)?v:[]).map(String).filter(x=>sets[k].has(x)))].slice(0,8)
export function sanitizePortfolioSimulation(input:any):{ventures:Venture[]}{
  const rows=Array.isArray(input?.ventures)?input.ventures:[]
  if(rows.length<1||rows.length>25)throw new Error('PORTFOLIO_SIZE')
  return{ventures:rows.map((r:any)=>{for(const k of ['archetype','stage','team_size','ai_spend'])if(!sets[k].has(String(r?.[k]||'')))throw new Error('INVALID_CATEGORY');return{archetype:String(r.archetype),stage:String(r.stage),team_size:String(r.team_size),ai_spend:String(r.ai_spend),objectives:list(r.objectives,'objectives'),capabilities:list(r.capabilities,'capabilities'),tools:list(r.tools,'tools'),constraints:list(r.constraints,'constraints')}})}
}
export function simulateSafePortfolio(raw:any){
  const{ventures}=sanitizePortfolioSimulation(raw)
  const counts=(k:MultiKey)=>ventures.reduce<Record<string,number>>((m,r)=>{for(const v of r[k])m[v]=(m[v]||0)+1;return m},{})
  const caps=counts('capabilities'),objectives=counts('objectives'),tools=counts('tools'),constraints=counts('constraints')
  const duplicates:Array<[string,number]>=[...Object.entries(caps),...Object.entries(objectives)].filter(([,n])=>n>1).sort((a,b)=>b[1]-a[1]).slice(0,6)
  const monthly=ventures.reduce((s,r)=>s+spend[r.ai_spend],0),weight=duplicates.reduce((s,[,n])=>s+n-1,0),savings=Math.round(monthly*Math.min(.46,.08+weight*.025))
  const vendors=['openai','anthropic','google_ai','local_models'].filter(k=>tools[k]),privacy=(constraints.privacy_first||0)+(constraints.regulated||0)+(constraints.data_residency||0),exposure=vendors.length<=1&&privacy?'high':vendors.length>=3?'contained':'moderate'
  const dependencies=Object.entries(caps).filter(([,n])=>n>1).slice(0,5).map(([capability])=>({capability,ventures:ventures.map((r,i)=>r.capabilities.includes(capability)?`Venture ${String(i+1).padStart(2,'0')}`:'').filter(Boolean)}))
  const actions:Array<{title:string;why:string;impact:string;confidence:number}>=[]
  if(duplicates[0])actions.push({title:`Create a shared ${label(duplicates[0][0])} capability`,why:`${duplicates[0][1]} ventures independently need the same operating pattern.`,impact:`$${Math.max(savings,100).toLocaleString()}/month directional savings`,confidence:Math.min(91,58+duplicates[0][1]*6)})
  if(exposure!=='contained')actions.push({title:'Route work through a context-isolated model fabric',why:`${vendors.length||1} AI vendor${vendors.length===1?'':'s'} concentrate portfolio context.`,impact:'Reduce single-vendor IP reconstruction risk',confidence:86})
  if(dependencies[0])actions.push({title:`Promote ${label(dependencies[0].capability)} into the capability passport`,why:`The pattern recurs across ${dependencies[0].ventures.length} ventures.`,impact:'One verified implementation, reusable portfolio-wide',confidence:82})
  for(const f of [{title:'Pool model purchasing and outcome routing',why:'Compare cost, quality, latency, and privacy portfolio-wide.',impact:'Lower unit cost without vendor lock-in',confidence:74},{title:'Establish a shared verification and release contract',why:'Common QA and rollback requirements remove repeated coordination.',impact:'Safer autonomous improvements',confidence:78}])if(actions.length<3)actions.push(f)
  return{portfolio_size:ventures.length,estimated_monthly_savings:savings,duplicate_patterns:duplicates.map(([pattern,n])=>({pattern,label:label(pattern),ventures:n})),hidden_dependencies:dependencies,ip_exposure:{level:exposure,ai_vendor_count:vendors.length,privacy_sensitive_ventures:privacy,recommendation:exposure==='contained'?'Maintain disclosure budgets and local joins.':'Fragment context by task and join sensitive results inside the founder boundary.'},coordinated_actions:actions.slice(0,3),privacy_receipt:{stored:false,company_names_requested:false,repositories_requested:false,customer_data_requested:false,secrets_requested:false,input_mode:'bounded_categories_only'},methodology:{type:'directional_pre_signup_simulation',confidence:'illustrative',caveat:'Decision-grade results require an authenticated, permissioned digital twin.'}}
}
