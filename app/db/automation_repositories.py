from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.secrets import SecretProtector
from app.db.database import Database, utc_now


class APITokenRepository:
    def __init__(self,database:Database,data_dir:Path,protector:SecretProtector|None=None)->None:
        self.db=database;self.path=data_dir/"secrets"/"local_api_token.protected";self.protector=protector or SecretProtector()

    @staticmethod
    def _hash(token:str)->str:return hashlib.sha256(token.encode()).hexdigest()

    def ensure_default(self)->str:
        if self.path.exists():token=self.protector.read_file(self.path)
        else:
            token="tnx_"+secrets.token_urlsafe(36);self.protector.write_file(self.path,token)
        with self.db.connection() as connection:
            connection.execute(
                "INSERT INTO api_tokens(id,name,token_hash,scopes_json,created_at) VALUES(?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET token_hash=excluded.token_hash,revoked_at=NULL",
                (str(uuid.uuid4()),"local-admin",self._hash(token),json.dumps(["read","write","publish"]),utc_now()),
            )
        return token

    def local_token(self)->str:return self.protector.read_file(self.path)

    def verify(self,token:str,required_scope:str)->dict[str,Any]|None:
        with self.db.connection() as connection:
            row=connection.execute("SELECT * FROM api_tokens WHERE token_hash=? AND revoked_at IS NULL",(self._hash(token),)).fetchone()
            if not row:return None
            scopes=json.loads(row["scopes_json"])
            if required_scope not in scopes:return None
            connection.execute("UPDATE api_tokens SET last_used_at=? WHERE id=?",(utc_now(),row["id"]))
            result=dict(row);result["scopes"]=scopes;result.pop("token_hash",None);return result


class WebhookRepository:
    def __init__(self,database:Database,protector:SecretProtector|None=None)->None:self.db=database;self.protector=protector or SecretProtector()

    def create(self,name:str,url:str,secret:str,events:list[str])->dict[str,Any]:
        item_id,now=str(uuid.uuid4()),utc_now()
        with self.db.connection() as connection:
            connection.execute("INSERT INTO webhook_subscriptions(id,name,url,secret_protected,events_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(item_id,name,url,self.protector.protect(secret),json.dumps(sorted(set(events))),now,now))
        return self.get(item_id)

    def get(self,item_id:str,include_secret:bool=False)->dict[str,Any]|None:
        with self.db.connection() as connection:row=connection.execute("SELECT * FROM webhook_subscriptions WHERE id=?",(item_id,)).fetchone()
        if not row:return None
        result=dict(row);result["events"]=json.loads(result.pop("events_json"))
        protected=result.pop("secret_protected")
        if include_secret:result["secret"]=self.protector.unprotect(protected)
        return result

    def list(self)->list[dict[str,Any]]:
        with self.db.connection() as connection:ids=[row[0] for row in connection.execute("SELECT id FROM webhook_subscriptions ORDER BY created_at DESC")]
        return [self.get(item_id) for item_id in ids]

    def delete(self,item_id:str)->bool:
        with self.db.connection() as connection:cursor=connection.execute("DELETE FROM webhook_subscriptions WHERE id=?",(item_id,))
        return cursor.rowcount>0

    def enqueue(self,event_type:str,payload:dict[str,Any])->int:
        now=utc_now();count=0
        with self.db.connection() as connection:
            rows=connection.execute("SELECT id,events_json FROM webhook_subscriptions WHERE enabled=1").fetchall()
            for row in rows:
                events=json.loads(row["events_json"])
                if event_type not in events and "*" not in events:continue
                connection.execute("INSERT INTO webhook_outbox(id,subscription_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",(str(uuid.uuid4()),row["id"],event_type,json.dumps(payload,ensure_ascii=False),now));count+=1
        return count

    def claim(self)->dict[str,Any]|None:
        now=utc_now()
        with self.db.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row=connection.execute("SELECT * FROM webhook_outbox WHERE status IN ('pending','retrying') AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY created_at LIMIT 1",(now,)).fetchone()
                if not row:connection.execute("COMMIT");return None
                connection.execute("UPDATE webhook_outbox SET status='sending',attempts=attempts+1 WHERE id=?",(row["id"],));connection.execute("COMMIT")
            except Exception:connection.execute("ROLLBACK");raise
        result=dict(row);result["payload"]=json.loads(result.pop("payload_json"));result["subscription"]=self.get(result["subscription_id"],True);return result

    def finish(self,item_id:str,error:str|None=None)->None:
        now=utc_now()
        with self.db.connection() as connection:
            row=connection.execute("SELECT attempts FROM webhook_outbox WHERE id=?",(item_id,)).fetchone()
            if not row:return
            if error and row["attempts"]<8:
                due=(datetime.now(timezone.utc)+timedelta(seconds=min(3600,30*2**(row["attempts"]-1)))).isoformat()
                connection.execute("UPDATE webhook_outbox SET status='retrying',next_attempt_at=?,last_error=? WHERE id=?",(due,error[:2000],item_id))
            elif error:connection.execute("UPDATE webhook_outbox SET status='failed',last_error=? WHERE id=?",(error[:2000],item_id))
            else:connection.execute("UPDATE webhook_outbox SET status='sent',sent_at=?,last_error=NULL WHERE id=?",(now,item_id))

    def outbox(self,limit:int=100)->list[dict[str,Any]]:
        with self.db.connection() as connection:return [dict(row) for row in connection.execute("SELECT * FROM webhook_outbox ORDER BY created_at DESC LIMIT ?",(limit,))]
