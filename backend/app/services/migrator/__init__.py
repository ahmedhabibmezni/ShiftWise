"""
ShiftWise Migrator service — final stage of the migration pipeline.

Pipeline position:
    Discovery -> Analyzer -> Converter -> [Migrator] -> Reporting

Responsibilities (executed inside the Celery worker):
    1. Provision a target PVC per disk in the tenant namespace.
    2. Run a populator Kubernetes Job that copies (and converts) the QCOW2
       sitting on the transit PVC into the target PVC, on the same cluster
       node, without going through the network or cdi-uploadproxy.
    3. Create the KubeVirt VirtualMachine referencing the populated PVCs.
    4. Drive status transitions CONFIGURING -> STARTING -> VERIFYING ->
       COMPLETED on the Migration row.

Why not CDI upload?
    The QCOW2 already lives on a cluster PVC (transit-pvc, RWX NFS). Routing
    the bytes through cdi-uploadproxy + an upload-pod would add 3 hops and
    HTTPS overhead for data already in the cluster. Forklift / MTV uses the
    same pod-mounts-both-PVCs pattern under the hood (virt-v2v-in-place).

Public entry point:
    from app.services.migrator.service import MigratorService
    MigratorService().run(db, migration_id)
"""

from app.services.migrator.service import MigratorService

__all__ = ["MigratorService"]
