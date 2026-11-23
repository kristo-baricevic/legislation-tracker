"use client";
import { useEffect, useRef, useState } from "react";
import { committeeRequest, type Committee, type CommitteeBill } from "@/lib/committees";
import { getTopics, type TopicItem } from "@/lib/api";
import RepresentativeAvatarBadge from "@/app/components/RepresentativeAvatarBadge";
import BillCard from "@/app/components/BillCard";
import DashboardBillReader from "@/app/components/DashboardBillReader";
import LoadingSpinner from "@/app/components/LoadingSpinner";
import styles from "./committees.module.css";

function usePages<T extends {id:number}>(path:string, enabled=true) {
  const [items,setItems]=useState<T[]>([]), [page,setPage]=useState(1), [revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(true),[error,setError]=useState(false),[more,setMore]=useState(false),[congress,setCongress]=useState<number>();
  useEffect(() => {
    if (!enabled) return;
    const controller=new AbortController();
    setLoading(true); setError(false);
    committeeRequest<T>(path,page,controller.signal).then(data => {
      if (controller.signal.aborted) return;
      setItems(old => [...new Map([...old,...data.results].map(item=>[item.id,item])).values()]);
      setMore(Boolean(data.next)); if(data.congress) setCongress(data.congress);
    }).catch(()=>{if(!controller.signal.aborted)setError(true);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[path,page,revision,enabled]);
  return {items,loading,error,more,congress,load:()=>{if(!loading&&!error&&more){setLoading(true);setPage(n=>n+1);}},retry:()=>setRevision(n=>n+1)};
}

function More({loading,error,more,load,retry,label}:{loading:boolean;error:boolean;more:boolean;load:()=>void;retry:()=>void;label:string}) {
  const ref=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    if(!ref.current||loading||error||!more||typeof IntersectionObserver==="undefined")return;
    const observer=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting))load();},{rootMargin:"120px"});
    observer.observe(ref.current);return()=>observer.disconnect();
  },[loading,error,more,load]);
  return <div ref={ref} className={styles.more}>
    {error ? <button onClick={retry}>Retry {label}</button> : loading ? <span role="status">Loading…</span> : more ? <button onClick={load}>More {label}</button> : null}
  </div>;
}

const roles:Record<string,string>={chair:"Chair",vice_chair:"Vice Chair",ranking_member:"Ranking Member"};
function CommitteeSection({committee,congress,topic}:{committee:Committee;congress:number;topic:string}) {
  const ref=useRef<HTMLElement>(null);
  const [visible,setVisible]=useState(false);
  useEffect(()=>{
    if(typeof IntersectionObserver==="undefined"){setVisible(true);return;}
    const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setVisible(true);observer.disconnect();}},{rootMargin:"300px"});
    if(ref.current)observer.observe(ref.current);return()=>observer.disconnect();
  },[]);
  const bills=usePages<CommitteeBill>(`/api/committees/${committee.id}/introduced-bills/?congress=${congress}${topic?`&topic_id=${topic}`:""}`,visible);
  return <section ref={ref} className={styles.committee} aria-labelledby={`committee-${committee.id}`}>
    <header className={styles.heading}><div>{committee.parent_name&&<small>{committee.parent_name}</small>}<h2 id={`committee-${committee.id}`}>{committee.name}</h2></div><span className={styles.chamber}>{committee.chamber}</span></header>
    <div className={styles.members} role="region" aria-label={`${committee.name} members`} tabIndex={0}>
      {committee.members.map(({representative:rep,role})=><div key={rep.id} className={styles.member}>
        <RepresentativeAvatarBadge id={rep.id} name={rep.name} congress={congress} representative={rep} notes={[rep.state,...(roles[role]?[roles[role]]:[])]}/>
        {roles[role]&&<span className={styles.role}>{roles[role]}</span>}
      </div>)}
      {!committee.members.length&&<p>Members unavailable.</p>}
    </div>
    <h3 className={styles.rowTitle}>Bills introduced</h3>
    <div className={styles.bills} role="region" aria-label={`${committee.name} bills introduced`} tabIndex={0}>
      {bills.items.map(bill=><div className={styles.bill} key={bill.id}><DashboardBillReader bill={bill}>{(summary,action,feedback,current)=><BillCard bill={current} summary={summary} footer={action} feedback={feedback}/>}</DashboardBillReader></div>)}
      {!bills.loading&&!bills.error&&!bills.items.length&&<p>No bills found.</p>}
      <More {...bills} label="bills"/>
    </div>
  </section>;
}

function Directory({query,topic}:{query:string;topic:string}) {
  const data=usePages<Committee>(`/api/committees/${query?`?${query}`:""}`);
  return <div className={styles.directory}>
    {!data.items.length&&data.loading ? <LoadingSpinner active label="Loading committees…"/> : data.items.map(committee=><CommitteeSection key={committee.id} committee={committee} congress={data.congress!} topic={topic}/>)}
    {!data.loading&&!data.error&&!data.items.length&&<p>No committees found.</p>}
    <More {...data} label="committees"/>
  </div>;
}

export default function CommitteesPage(){
  const [chamber,setChamber]=useState("");
  const [topic,setTopic]=useState(""),[topics,setTopics]=useState<TopicItem[]>([]);
  const [topicError,setTopicError]=useState(false),[topicRevision,setTopicRevision]=useState(0);
  useEffect(()=>{let active=true;setTopicError(false);getTopics().then(items=>{if(!Array.isArray(items))throw new Error("Invalid topics");if(active)setTopics(items);}).catch(()=>{if(active)setTopicError(true);});return()=>{active=false;};},[topicRevision]);
  const [search,setSearch]=useState(""),[member,setMember]=useState(""),[level,setLevel]=useState("");
  const [text,setText]=useState({search:"",member:""});
  useEffect(()=>{const timer=setTimeout(()=>setText({search:search.trim(),member:member.trim()}),300);return()=>clearTimeout(timer);},[search,member]);
  const params=new URLSearchParams();
  if(chamber)params.set("chamber",chamber);
  if(text.search)params.set("search",text.search);
  if(text.member)params.set("member",text.member);
  if(level)params.set("level",level);
  if(topic)params.set("topic_id",topic);
  const query=params.toString();
  function clear(){setChamber("");setSearch("");setMember("");setLevel("");setTopic("");setText({search:"",member:""});}
  return <main className={styles.page}><div className={styles.toolbar}><h1>Committees</h1></div>
    <div className={styles.filters} role="search" aria-label="Committee filters">
      <label>Committee name<input type="search" value={search} maxLength={200} onChange={e=>setSearch(e.target.value)} placeholder="Search committees"/></label>
      <label>Member name<input type="search" value={member} maxLength={200} onChange={e=>setMember(e.target.value)} placeholder="Search members"/></label>
      <label>Topic{topicError?<button type="button" onClick={()=>setTopicRevision(n=>n+1)}>Retry topics</button>:<select value={topic} onChange={e=>setTopic(e.target.value)} disabled={!topics.length}><option value="">All topics</option>{topics.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select>}</label>
      <label>Chamber<select value={chamber} onChange={e=>setChamber(e.target.value)}><option value="">All</option><option value="senate">Senate</option><option value="house">House</option><option value="joint">Joint</option></select></label>
      <label>Type<select value={level} onChange={e=>setLevel(e.target.value)}><option value="">All</option><option value="committee">Committees</option><option value="subcommittee">Subcommittees</option></select></label>
      <button type="button" onClick={clear} disabled={!chamber&&!search&&!member&&!level&&!topic}>Clear filters</button>
    </div><Directory key={query} query={query} topic={topic}/></main>;
}
