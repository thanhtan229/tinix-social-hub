from __future__ import annotations

import os
from typing import Any

from app.runtime.contracts import BrowserRuntime, DurableQueue, ManagedStorage, SecretStore, StateDatabase


def runtime_report(*,database:Any,queue:Any,storage:Any,secrets:Any,browser:Any)->dict[str,Any]:
    contracts={
        "database":isinstance(database,StateDatabase),"queue":isinstance(queue,DurableQueue),
        "storage":isinstance(storage,ManagedStorage),"secrets":isinstance(secrets,SecretStore),
        "browser":isinstance(browser,BrowserRuntime),
    }
    blockers=[]
    if type(database).__name__=="Database":blockers.append("Thay SQLite bằng PostgreSQL adapter dùng cùng StateDatabase contract.")
    if type(storage).__name__=="LocalPathStorage":blockers.append("Thay local filesystem bằng object-storage adapter có staging file cho Chrome upload.")
    if os.name=="nt":blockers.append("Chọn secret backend server-side thay cho Windows DPAPI.")
    blockers.append("Cung cấp remote Chrome/CDP worker có ownership, lease và profile isolation.")
    blockers.append("Bảo vệ toàn bộ WebUI/API trước khi bind ra ngoài loopback.")
    return {
        "profile":"pc-first","host_os":os.name,"contracts":contracts,
        "contract_ready":all(contracts.values()),"vps_deployable":not blockers,"vps_blockers":blockers,
        "active_backends":{"database":type(database).__name__,"queue":type(queue).__name__,"storage":type(storage).__name__,"secrets":type(secrets).__name__,"browser":type(browser).__name__},
    }
