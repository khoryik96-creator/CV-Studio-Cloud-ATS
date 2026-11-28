"""Exercise real local HTTPS, session, queue and automatic worker."""
import http.client
import io
import json
import ssl
import sys
import time
import zipfile
from http.cookies import SimpleCookie
from uuid import UUID, uuid4
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

def wait_for_output(path, auth):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        state = json.loads(expect("GET", path, 200, headers=auth)[2])["state"]
        if state in ("succeeded", "needs_review"):
            return state
        if state == "failed":
            raise RuntimeError("Synthetic job failed")
        time.sleep(2)
    raise RuntimeError("Automatic worker did not finish")


def check_blinding(document_id, auth, other):
    data = json.dumps({
        "document_id": document_id,
        "module": "cv_blinding",
        "neutral_gender": True,
        "idempotency_key": str(uuid4()),
    })
    job = json.loads(expect("POST", "/api/jobs", 202, data,
                            {**auth, "Content-Type": "application/json"})[2])
    path = "/api/jobs/" + job["job_id"]
    assert wait_for_output(path, auth) == "needs_review"
    expect("GET", path + "/preview", 409, headers=auth)
    expect("GET", path + "/download", 409, headers=auth)
    expect("GET", path + "/download?review=1", 404, headers=other)
    raw = expect("GET", path + "/download?review=1", 200, headers=auth)[2]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        xml = archive.read("word/document.xml").lower()
        assert b"disaster recovery automation" in xml
        assert b"automated recovery checks with ansible" in xml
        for entry in archive.namelist():
            if not entry.endswith((".xml", ".rels")):
                continue
            data = archive.read(entry).lower()
            for identifier in (b"avery example", b"avery@example.invalid", b"+60 10 000 0000",
                               b"example cloud sdn bhd", b"example systems sdn bhd",
                               b"example technical university"):
                assert identifier not in data
    print("Synthetic HTTPS blinding and human review passed", file=sys.stderr)


def check_persistence(job_id):
    job_id = str(UUID(job_id))
    path = "/api/jobs/" + job_id
    auth = login("fictional")
    job = json.loads(expect("GET", path, 200, headers=auth)[2])
    assert job["state"] in ("succeeded", "needs_review")
    history = json.loads(expect("GET", "/api/jobs", 200, headers=auth)[2])
    assert any(item["job_id"] == job_id and item["output_available"] for item in history["items"])
    documents = json.loads(expect("GET", "/api/documents", 200, headers=auth)[2])
    assert any(item["document_id"] == job["document_id"] for item in documents["items"])
    preview = json.loads(expect("GET", path + "/preview?review=1", 200, headers=auth)[2])
    assert any("Disaster Recovery Automation" in line for line in preview["paragraphs"])
    expect("GET", path + "/download?review=1", 200, headers=auth)
    other = login("fictional-other")
    expect("GET", path + "/preview?review=1", 404, headers=other)
    resumed = json.dumps({"document_id": job["document_id"], "module": "cv_formatting",
                          "idempotency_key": str(uuid4())})
    next_job = json.loads(expect("POST", "/api/jobs", 202, resumed,
                                 {**auth, "Content-Type": "application/json"})[2])["job_id"]
    next_path = "/api/jobs/" + next_job
    wait_for_output(next_path, auth)
    expect("GET", next_path + "/download?review=1", 200, headers=auth)
    expect("POST", "/api/auth/logout", 200, headers=auth)
    expect("POST", "/api/auth/logout", 200, headers=other)
    print("Synthetic HTTPS history and downloads persisted, and the recreated worker processed a job")


def main():
    if len(sys.argv)==2 and sys.argv[1]=="health":
        expect("GET","/healthz",200)
        return
    if len(sys.argv) == 3 and sys.argv[1] == "persistence":
        check_persistence(sys.argv[2])
        return
    page=expect("GET","/cloud-ui",200)[2]
    assert b'id="btnFormat"' in page
    assert b'/cloud-ui/assets/batch_cloud.js' in page
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
    wait_for_output(path, auth)
    raw=expect("GET",path+"/download?review=1",200,headers=auth)[2]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        xml=archive.read("word/document.xml")
        assert b"Disaster Recovery Automation" in xml and b"9,000" not in xml
    expect("GET",path+"/download?review=1",404,headers=other)
    other_doc=json.loads(expect("POST","/api/documents",201,fixture,{**other,"Content-Type":"text/plain"})[2])["document_id"]
    other_job=json.loads(expect("POST","/api/jobs",202,json.dumps({"document_id":other_doc,"module":"cv_formatting",
        "idempotency_key":str(uuid4())}),{**other,"Content-Type":"application/json"})[2])["job_id"]
    other_path="/api/jobs/"+other_job
    expect("GET",other_path,404,headers=auth)
    wait_for_output(other_path, other)
    expect("GET",other_path+"/download?review=1",200,headers=other)
    check_blinding(doc, auth, other)
    expect("POST","/api/auth/logout",200,headers=auth)
    expect("GET",path,401,headers=auth)
    expect("POST","/api/auth/logout",200,headers=other)
    print("Synthetic HTTPS worker workflow passed", file=sys.stderr)
    print(job)

if __name__=="__main__":
    main()
