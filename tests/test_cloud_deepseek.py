import json
import unittest
from cloud.deepseek import DeepSeekTransport,HOST,PATH
from cloud.ai_dispatch import DispatchError

class Response:
    def __init__(self,body,status=200):
        self.body=json.dumps(body).encode()
        self.status=status
    def read(self,n):
        return self.body[:n]

class Connection:
    def __init__(self,response):
        self.response=response
        self.calls=[]
        self.closed=False
    def request(self,*args,**kwargs):
        self.calls.append((args,kwargs))
    def getresponse(self):
        return self.response
    def close(self):
        self.closed=True

class TestDeepSeek(unittest.TestCase):
    def call(self,body,status=200):
        conn=Connection(Response(body,status))
        def factory(host,port,**kwargs):
            self.assertEqual((host,port),(HOST,443))
            return conn
        return conn,DeepSeekTransport("fictional-key",connection_factory=factory)
    def test_success_and_usage(self):
        conn,transport=self.call({"choices":[{"finish_reason":"stop","message":{"content":"{}"}}],"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6}})
        answer=transport("deepseek","synthetic-model","system","user",10)
        self.assertEqual((answer.text,answer.input_tokens,answer.output_tokens),("{}",4,2))
        self.assertEqual(conn.calls[0][0],("POST",PATH))
        self.assertFalse(json.loads(conn.calls[0][1]["body"])["stream"])
        self.assertTrue(conn.closed)
    def test_truncation_is_billed(self):
        conn,transport=self.call({"choices":[{"finish_reason":"length","message":{"content":"{"}}],"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6}})
        self.assertEqual(transport("deepseek","synthetic-model","system","user",10).text,"")
    def test_no_retry_on_http_error(self):
        conn,transport=self.call({},429)
        with self.assertRaises(DispatchError):
            transport("deepseek","synthetic-model","system","user",10)
        self.assertEqual(len(conn.calls),1)
        self.assertTrue(conn.closed)
