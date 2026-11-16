"""Deliberately limited local adapter, not an LLM: exact text replacement."""
import re
from transactions import Rejected
_PATTERN=re.compile(r'^把「([\s\S]+)」替换为「([\s\S]*)」$')
def replace_text(context,instruction):
 m=_PATTERN.fullmatch(instruction)
 if not m:raise Rejected('本地替换格式：把「原文」替换为「新文」。此适配器不是 AI。')
 old,new=m.groups();count=context.text.count(old)
 if count!=1:raise Rejected('原文必须恰好匹配一处；实际为 '+str(count)+' 处')
 return {'new_text':context.text.replace(old,new,1),'adapter':'local-exact-replacement-v1 (not AI)','summary':'替换唯一匹配的文本；等待独立确认应用'}
