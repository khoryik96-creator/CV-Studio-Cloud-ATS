"""Tenant-scoped operator-curated research. No arbitrary URL retrieval.

The catalogue contains reviewed excerpts, not a claim of live verification.
No global fallback, fuzzy matches, external requests or secrets in results.
"""
from types import MappingProxyType
import unicodedata
from cloud.company_profile_contract import Source, _validate_sources, _text
from cloud.documents_jobs import uid
from cloud.auth import Principal
from cloud.deploy.workspace_config import read_json_file

def company_key(name):
    name=_text(name,200)
    return " ".join(unicodedata.normalize("NFKC",name).casefold().split())

class ApprovedResearch:
    def __init__(self, records):
        if not isinstance(records,list) or not 1<=len(records)<=100:
            raise ValueError("Approved research catalogue required")
        entries={}
        for row in records:
            if not isinstance(row,dict) or set(row)!={"tenant_id","company_name","sources"}:
                raise ValueError("Invalid research entry")
            key=(uid(row["tenant_id"]),company_key(row["company_name"]))
            if key in entries or not isinstance(row["sources"],list):
                raise ValueError("Duplicate or invalid research entry")
            sources=[]
            for source in row["sources"]:
                if not isinstance(source,dict) or set(source)!={"id","title","text","url","retrieved_on"}:
                    raise ValueError("Invalid approved source")
                if not isinstance(source["url"],str) or not source["url"].startswith("https://") or not source["retrieved_on"]:
                    raise ValueError("HTTPS citation and dated excerpt required")
                sources.append(Source(**source))
            _validate_sources(sources)
            entries[key]=tuple(sources)
        self._entries=MappingProxyType(entries)

    def __call__(self, principal, company_name):
        if not isinstance(principal,Principal):
            raise ValueError("Trusted research principal required")
        try:
            return self._entries[(uid(principal.tenant_id),company_key(company_name))]
        except KeyError:
            raise ValueError("No approved sources for this organisation and company") from None

def load_research():
    return ApprovedResearch(read_json_file("CVCLOUD_RESEARCH_CATALOGUE_FILE",max_bytes=2*1024*1024))
