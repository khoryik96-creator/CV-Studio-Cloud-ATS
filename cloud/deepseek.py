"""Fixed-endpoint DeepSeek Chat Completions adapter. No retries or redirects."""
from __future__ import annotations
import http.client
import json
import ssl
from cloud.ai_dispatch import Completion, DispatchError, _tokens
from cloud.ai_budget import model_id

HOST = "api.deepseek.com"
PATH = "/chat/completions"
MAX_RESPONSE = 4 * 1024 * 1024
MAX_REQUEST = 2 * 1024 * 1024

class DeepSeekTransport:
    def __init__(self, secret, *, timeout=60, connection_factory=None):
        if not isinstance(secret,str) or not 1 <= len(secret) <= 4096 or any(not 33 <= ord(c) <= 126 for c in secret):
            raise ValueError("Invalid provider credential")
        if type(timeout) is not int or not 1 <= timeout <= 90:
            raise ValueError("Invalid provider timeout")
        self._secret=secret
        self._timeout=timeout
        self._connect=connection_factory or http.client.HTTPSConnection

    def __call__(self,provider,model,system,user,limit):
        model_id(provider,model)
        if provider!="deepseek" or not isinstance(system,str) or not isinstance(user,str) or not 1<=_tokens(limit):
            raise DispatchError("invalid_deepseek_request")
        payload=json.dumps({"model":model,"messages":[{"role":"system","content":system},{"role":"user","content":user}],
            "max_tokens":limit,"stream":False,"response_format":{"type":"json_object"}},ensure_ascii=False,allow_nan=False).encode("utf-8")
        if len(payload)>MAX_REQUEST:
            raise DispatchError("deepseek_request_limit")
        conn=None
        try:
            conn=self._connect(HOST,443,timeout=self._timeout,context=ssl.create_default_context())
            conn.request("POST",PATH,body=payload,headers={"Authorization":"Bearer "+self._secret,
                "Content-Type":"application/json","Accept":"application/json","Accept-Encoding":"identity"})
            response=conn.getresponse()
            if response.status!=200:
                raise DispatchError("deepseek_http_failure")
            data=response.read(MAX_RESPONSE+1)
            if len(data)>MAX_RESPONSE:
                raise DispatchError("deepseek_response_limit")
            body=json.loads(data)
            usage=body["usage"]
            used_input=_tokens(usage["prompt_tokens"])
            used_output=_tokens(usage["completion_tokens"])
            if used_input+used_output!=_tokens(usage["total_tokens"]):
                raise DispatchError("deepseek_usage_mismatch")
            # A truncated/refused answer may still be billed. Return empty text
            # with reported usage so dispatch settles it before JSON rejection.
            choices=body.get("choices")
            text=""
            if isinstance(choices,list) and len(choices)==1 and isinstance(choices[0],dict):
                choice=choices[0]
                message=choice.get("message")
                if choice.get("finish_reason")=="stop" and isinstance(message,dict) and isinstance(message.get("content"),str) and not message.get("tool_calls"):
                    text=message["content"]
            return Completion(text,used_input,used_output)
        except Exception:
            raise DispatchError("deepseek_outcome_requires_review") from None
        finally:
            if conn is not None:
                conn.close()
