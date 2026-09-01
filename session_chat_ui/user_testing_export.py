"""Dependency-free multi-sheet Excel export for user testing."""
import json, os, re, tempfile, threading, zipfile
from pathlib import Path
from xml.sax.saxutils import escape

POST = (("How would you describe your experience with the robot?","experience_with_robot"),("Do you have any other questions or feedback?","other_feedback"),("From the explanation, I know how the robot works.","satisfaction_1_know_how"),("This explanation of how the robot works is satisfying.","satisfaction_2_satisfying"),("This explanation of how the robot works has sufficient detail.","satisfaction_3_sufficient_detail"),("This explanation of how the robot works seems complete.","satisfaction_4_complete"),("This explanation of how the robot works tells me how to use it.","satisfaction_5_how_to_use"),("This explanation of how the robot works is useful to my goals.","satisfaction_6_useful_to_goals"),("This explanation of the robot shows me how accurate the robot is.","satisfaction_7_accuracy"),("I am confident in the robot. I feel that it works well.","trust_1_confident"),("The outputs of the robot are very predictable.","trust_2_predictable"),("The tool is very reliable. I can count on it to be correct all the time.","trust_3_reliable"),("I feel safe that when I rely on the robot I will get the right answers.","trust_4_safe"),("The robot is efficient in that it works very quickly.","trust_5_efficient"),("I am wary of the robot.","trust_6_wary"))
CHAT = (("User ID","user_id"),("Timestamp (UTC)","timestamp_utc"),("Session ID","session_id"),("Displayed system","system_slot"),("Backend system","backend_system"),("Question","question"),("Robot response","robot_response"),("Chat status","chat_status"),("What were you hoping to clarify with that question?","hoped_to_clarify"),("What was particularly helpful about the response?","helpful"),("What was unclear about the response?","unclear"),("What information was still missing?","missing"))
PRE = (("User ID","user_id"),("Timestamp (UTC)","timestamp_utc"),("Session ID","session_id"),("Question","question"),("Answer","answer"))
INTERVIEW_FIELDS = ("hoped_to_clarify", "helpful", "unclear", "missing")
LEGACY_INTERVIEW_PATTERN = re.compile(
 r"(?:\A|\n\n)Question: (?P<question>.*?)\n"
 r"Response: (?P<robot_response>.*?)\n"
 r"Hoped to clarify: (?P<hoped_to_clarify>.*?)\n"
 r"Helpful: (?P<helpful>.*?)\n"
 r"Unclear: (?P<unclear>.*?)\n"
 r"Missing: (?P<missing>.*?)(?=\n\nQuestion: |\Z)",
 re.DOTALL,
)


def legacy_interviews(record, chats):
 """Recover structured interview answers from older combined-text records."""
 text = record.get("per_question_interviews", "")
 if not isinstance(text, str) or not text:
  return []

 user_id = str(record.get("user_id", ""))
 session_id = str(record.get("session_id", ""))
 matched_request_ids = set()
 interviews = []
 for match in LEGACY_INTERVIEW_PATTERN.finditer(text):
  values = match.groupdict()
  request_id = next(
   (
    candidate_id
    for candidate_id, chat in chats.items()
    if candidate_id not in matched_request_ids
    and str(chat.get("user_id", "")) == user_id
    and str(chat.get("session_id", "")) == session_id
    and str(chat.get("question", "")) == values["question"]
    and str(chat.get("robot_response", "")) == values["robot_response"]
   ),
   None,
  )
  if request_id is None:
   continue
  matched_request_ids.add(request_id)
  interviews.append(
   {
    "request_id": request_id,
    **{field: values[field] for field in INTERVIEW_FIELDS},
   }
  )
 return interviews


def col(n):
 s=""
 while n:n,r=divmod(n-1,26);s=chr(65+r)+s
 return s
def cell(ref,v,style):
 t="" if v is None else str(v);t="".join(c for c in t if c in "\t\n\r" or ord(c)>=32)[:32767]
 return '<c r="{}" s="{}" t="inlineStr"><is><t xml:space="preserve">{}</t></is></c>'.format(ref,style,escape(t))
class UserTestingExcelLogger:
 def __init__(self,path,pre_chat_questions=()):
  self.path=Path(path).resolve();self.log=self.path.with_suffix(".jsonl");self.questions=tuple(pre_chat_questions);self.lock=threading.Lock();self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 def append(self,record):
  with self.lock:
   with self.log.open("a",encoding="utf-8") as f:f.write(json.dumps(record,ensure_ascii=False)+"\n");f.flush();os.fsync(f.fileno())
   self.build()
 def records(self):
  if not self.log.exists():return []
  return [json.loads(x) for x in self.log.read_text(encoding="utf-8").splitlines() if x]
 def sheet(self,headers,rows):
  out=['<row r="1">'+''.join(cell(col(i)+"1",h,1) for i,h in enumerate(headers,1))+'</row>']
  for r,row in enumerate(rows,2):out.append('<row r="{}">{}</row>'.format(r,''.join(cell(col(i)+str(r),row.get(h,""),2) for i,h in enumerate(headers,1))))
  return '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" state="frozen"/></sheetView></sheetViews><sheetData>{}</sheetData><autoFilter ref="A1:{}{}"/></worksheet>'.format(''.join(out),col(len(headers)),max(1,len(rows)+1))
 def build(self):
  rec=self.records();users={};chats={};order=[];pre_rows=[]
  for x in rec:
   if x.get("event_type")=="chat" and x.get("request_id"):
    request_id=str(x["request_id"])
    chats[request_id]=dict(x);order.append(request_id)
  for x in rec:
   u=str(x.get("user_id",""));
   if not u:continue
   row=users.setdefault(u,{"User ID":u});row["Timestamp (UTC)"]=x.get("timestamp_utc","");row["Session ID"]=x.get("session_id","")
   if x.get("event_type")=="pre_chat_survey":
    answers=x.get("pre_chat_answers",())
    if answers:
     for i,item in enumerate(answers):
      if isinstance(item,dict):
       question=item.get("question","")
       answer=item.get("answer","")
      else:
       question=self.questions[i] if i<len(self.questions) else ""
       answer=item
      if question:
       pre_rows.append({"User ID":u,"Timestamp (UTC)":x.get("timestamp_utc",""),"Session ID":x.get("session_id",""),"Question":question,"Answer":answer})
      if i<len(self.questions):row[self.questions[i]]=answer
   if x.get("event_type")=="post_chat_feedback":
    for _,k in POST:row[k]=x.get(k,"")
    interviews=x.get("interviews",[])
    if not isinstance(interviews,list) or not interviews:
     interviews=legacy_interviews(x,chats)
    for a in interviews:
     if not isinstance(a,dict):continue
     request_id=str(a.get("request_id",""))
     chat=chats.get(request_id)
     if chat is None:continue
     if str(chat.get("user_id",""))!=u or str(chat.get("session_id",""))!=str(x.get("session_id","")):continue
     for field in INTERVIEW_FIELDS:chat[field]=a.get(field,"")
  sh1=("User ID","Timestamp (UTC)","Session ID")+self.questions+tuple(h for h,_ in POST)
  for row in users.values():
   for h,k in POST:row[h]=row.pop(k,"")
  sh2=tuple(h for h,_ in CHAT)
  rows2=[]
  for k in order:
   row=chats[k]
   for h,key in CHAT:row[h]=row.get(key,"")
   rows2.append(row)
  sh3=tuple(h for h,_ in PRE)
  fd,tmp=tempfile.mkstemp(dir=str(self.path.parent),suffix=".tmp");os.close(fd)
  try:
   with zipfile.ZipFile(tmp,"w",zipfile.ZIP_DEFLATED) as z:
    z.writestr("[Content_Types].xml",'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
    z.writestr("_rels/.rels",'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    z.writestr("xl/workbook.xml",'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Participant summary" sheetId="1" r:id="rId1"/><sheet name="Chat interactions" sheetId="2" r:id="rId2"/><sheet name="Pre-chat survey" sheetId="3" r:id="rId3"/></sheets></workbook>')
    z.writestr("xl/_rels/workbook.xml.rels",'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/></Relationships>')
    z.writestr("xl/worksheets/sheet1.xml",self.sheet(sh1,users.values()));z.writestr("xl/worksheets/sheet2.xml",self.sheet(sh2,rows2));z.writestr("xl/worksheets/sheet3.xml",self.sheet(sh3,pre_rows))
   os.replace(tmp,self.path)
  finally:
   if os.path.exists(tmp):os.unlink(tmp)
