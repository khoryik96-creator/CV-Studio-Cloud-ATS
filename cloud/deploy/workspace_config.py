"""Explicit, file-based online workspace configuration. No default provider prices."""
import json
import os
from pathlib import Path
from cloud.ai_dispatch import ModelPolicy
from cloud.ai_secrets import SecretCipher
from cloud.provider_config import ProviderCatalogue
from cloud.deploy.online_init import connect_as, read_secret
from cloud.deploy.workspace_roles import ROLES_BY_SERVICE

def read_json_file(env_name, *, max_bytes=65536):
    value=os.environ.get(env_name,"")
    path=Path(value)
    if not value or not path.is_absolute():
        raise ValueError("Absolute configuration file required")
    with path.open("rb") as source:
        raw=source.read(max_bytes+1)
    if not raw or len(raw)>max_bytes:
        raise ValueError("Invalid configuration size")
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:
                raise ValueError("Duplicate configuration key")
            result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=unique)

def load_policy():
    keyring=read_json_file("CVCLOUD_KEYRING_FILE")
    if not isinstance(keyring,dict) or set(keyring)!={"active_version","keys"} or not isinstance(keyring["keys"],dict):
        raise ValueError("Invalid keyring")
    if not 1<=len(keyring["keys"])<=16:
        raise ValueError("Invalid keyring size")
    keys={name:bytes.fromhex(value) for name,value in keyring["keys"].items()}
    cipher=SecretCipher(keys,keyring["active_version"])
    config=read_json_file("CVCLOUD_MODEL_CATALOGUE_FILE")
    fields={"provider","model","input_rate","output_rate","max_input_tokens","max_output_tokens"}
    if not isinstance(config,list) or not 1<=len(config)<=100 or any(not isinstance(p,dict) or set(p)!=fields for p in config):
        raise ValueError("Explicit priced model catalogue required")
    return cipher,ProviderCatalogue([ModelPolicy(**p) for p in config])

def service_connection(service):
    role=ROLES_BY_SERVICE[service]
    secret=read_secret("CVCLOUD_"+service.upper()+"_PASSWORD_FILE")
    return lambda:connect_as(role,secret)

def concurrency():
    value=os.environ.get("CVCLOUD_WORKER_CONCURRENCY","2")
    if value not in ("1","2","3","4"):
        raise ValueError("Worker concurrency must be 1 to 4")
    return int(value)

def require_live_worker_approval():
    if os.environ.get("CVCLOUD_LIVE_AI")!="operator-approved":
        raise RuntimeError("Live AI worker disabled pending explicit approval")
