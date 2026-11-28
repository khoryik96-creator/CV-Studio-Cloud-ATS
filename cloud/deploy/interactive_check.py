"""Exercise real local HTTPS, session, queue and automatic worker."""
import http.client
import io
import json
import ssl
import sys
import time
import zipfile
from http.cookies import SimpleCookie
from uuid import uuid4
from cloud.deploy.interactive import CERT, HOST, ORIGIN, ROOT, EMAIL, PASSWORD

def request(method,path,body=None,headers=None):
    context=ssl.create_default_context(cafile=CERT)
    conn=http.client.HTTPSConnection(HOST,8443,timeout=10,context=context)
    try:
        conn.request(method,path,body=body,headers={"Host":HOST,**(headers or {})})
        response=conn.getresponse()
        return response.status,dict(response.getheaders()),response.read()
    finally:
        conn.close()

def expect(method,path,status,body=None,headers=None):
    result=request(method,path,body,headers)
    if result[0]!=status:
        raise RuntimeError(f"{method} {path}: expected {status}, got {result[0]}")
    return result

def login(tenant):
    _,headers,_=expect("POST","/api/auth/login",200,json.dumps({"tenant":tenant,"email":EMAIL,"password":PASSWORD}),
        {"Content-Type":"application/json","Origin":ORIGIN})
    cookie=SimpleCookie();cookie.load(headers["Set-Cookie"])
    auth={"Cookie":"__Host-cvcloud="+cookie["__Host-cvcloud"].value}
    me=json.loads(expect("GET","/api/auth/me",200,headers=auth)[2])
    return {**auth,"Origin":ORIGIN,"X-CSRF-Token":me["csrf"]}

def main():
    if len(sys.argv)==2 and sys.argv[1]=="health":
        expect("GET","/healthz",200)
        return
    page=expect("GET","/cloud-ui",200)[2]
    assert b'id="btnFormat"' in page
    expect("GET","/readyz",503)
    expect("GET","/api/auth/me",401)
    expect("GET","/jobadder",404)
    auth=login("fictional")
    other=login("fictional-other")
    fixture=(ROOT/"tests/fixtures/cloud_cv_source.txt").read_bytes()
    expect("POST","/api/documents",400,b"not a fixture",{**auth,"Content-Type":"text/plain"})
    doc=json.loads(expect("POST","/api/documents",201,fixture,{**auth,"Content-Type":"text/plain"})[2])["document_id"]
    job=json.loads(expect("POST","/api/jobs",202,json.dumps({"document_id":doc,"module":"cv_formatting",
        "alignment":"justify","idempotency_key":str(uuid4())}),{**auth,"Content-Type":"application/json"})[2])["job_id"]
    path="/api/jobs/"+job
    expect("GET",path,404,headers=other)
    end=time.monotonic()+120
    while time.monotonic()<end:
        state=json.loads(expect("GET",path,200,headers=auth)[2])["state"]
        if state=="succeeded":
            break
        if state=="needs_review":
            # A review-flagged result may still have a downloadable artifact.
            break
        if state=="failed":
            raise RuntimeError("Synthetic job failed")
        time.sleep(2)
    else:
        raise RuntimeError("Automatic worker did not finish")
    raw=expect("GET",path+"/download?review=1",200,headers=auth)[2]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        xml=archive.read("word/document.xml")
        assert b"Disaster Recovery Automation" in xml and b"9,000" not in xml
    expect("GET",path+"/download?review=1",404,headers=other)
    expect("POST","/api/auth/logout",200,headers=auth)
    expect("GET",path,401,headers=auth)
    print("Synthetic HTTPS worker workflow passed")

if __name__=="__main__":
    main()
