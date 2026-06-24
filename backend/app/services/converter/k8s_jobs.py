"""
In-cluster Kubernetes Job runner for the converter pipeline.

Why in-cluster? See design Q2 — virt-v2v needs ``libguestfs`` and ``/dev/kvm``;
running it in a privileged Pod inside ``shiftwise-converter`` namespace is
the same security boundary as KubeVirt itself, scales horizontally, and avoids
running root subprocess on the NFS host.

Public API:
    runner = ConversionJobRunner()
    job_name = runner.submit_qemu_img(...)        # or submit_virt_v2v(...)
    final = runner.wait_for_completion(job_name)  # blocks; returns terminal status
    logs   = runner.get_logs(job_name)
    runner.delete(job_name)

The runner does not touch the DB — the converter service is responsible for
mapping ``final`` and ``logs`` onto :class:`ConversionJob` and
:class:`ConversionAttempt`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from kubernetes.client.rest import ApiException

from app.core.config import settings
from app.core.kubevirt_client import get_kubevirt_client
from app.services.converter.errors import ConversionError

logger = logging.getLogger(__name__)


# Labels stamped on every Job we create — used for selectors + cleanup sweeps.
_LABEL_APP = "app.shiftwise.io/component"
_LABEL_APP_VAL = "converter"
_LABEL_GROUP = "app.shiftwise.io/group"
_LABEL_DISK = "app.shiftwise.io/disk-index"

# Audit E9 — client-side HTTP timeout for poll-loop K8s reads. Without it a
# hung API server (no FIN, no RST) wedges the worker thread inside a single
# read forever, defeating the loop-level deadline. 30 s is well under the
# 5 s poll interval's intent yet generous for a healthy apiserver.
_K8S_READ_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class JobOutcome:
    """Terminal outcome of a Kubernetes Job."""
    succeeded: bool
    failure_reason: Optional[str]   # k8s-side reason, e.g. "BackoffLimitExceeded"
    container_exit_code: Optional[int]


def _qemu_img_convert_cmd(
    *,
    target_format: str,
    input_path: str,
    output_path: str,
    source_format: str = "",
) -> list[str]:
    """Build the ``qemu-img convert`` command list.

    Adds ``-f <source_format>`` only when *source_format* is ``"raw"``
    (case-insensitive).  For every other value the produced command is
    byte-for-byte identical to the no-flag baseline, preserving backward
    compatibility with existing connectors that stage qcow2/vmdk/vhd files
    whose magic headers are reliably auto-detected by qemu-img.

    RAW disk images produced by ``dd | gzip`` → gunzip lack a magic header
    (the first sector is a filesystem superblock) so auto-detection is
    unreliable and must be suppressed with an explicit ``-f raw``.
    """
    src_flag: list[str] = ["-f", source_format] if source_format.lower() == "raw" else []
    cmd = [
        "qemu-img", "convert", "-p",
        *src_flag,
        "-O", target_format,
        "-o", "compat=1.1,cluster_size=65536" if target_format == "qcow2" else "",
        input_path, output_path,
    ]
    # Drop empty -o argument when not qcow2.
    return [c for c in cmd if c != ""]


class ConversionJobRunner:
    """Submit + observe Kubernetes Jobs that perform disk conversion."""

    def __init__(self) -> None:
        self._kv = get_kubevirt_client()
        self._namespace = settings.CONVERTER_K8S_NAMESPACE
        self._image = settings.CONVERTER_CONTAINER_IMAGE
        self._pvc_name = settings.CONVERTER_TRANSIT_PVC

    # --- Submission ---------------------------------------------------------

    def submit_qemu_img(
        self,
        *,
        job_name: str,
        group_uuid: str,
        disk_index: int,
        input_path: str,
        output_path: str,
        target_format: str,
        source_format: str = "",
        backoff_limit: int = 0,        # we manage retries at the DB layer
        active_deadline_seconds: int = 6 * 3600,  # 6h hard cap
    ) -> str:
        """Submit a Job that runs ``qemu-img convert -p [-f <src_fmt>] -O <fmt> <in> <out>``.

        ``source_format`` is only passed through to the command when it equals
        ``"raw"`` (case-insensitive).  All other values leave the command
        unchanged so existing connectors (KVM, Proxmox, vSphere, oVirt, Hyper-V,
        VMware Workstation) that stage qcow2/vmdk/vhd files are unaffected.

        Returns the submitted Job name. Both input and output paths must lie
        inside the mounted transit PVC.
        """
        cmd = _qemu_img_convert_cmd(
            target_format=target_format,
            input_path=input_path,
            output_path=output_path,
            source_format=source_format,
        )
        return self._submit_job(
            job_name=job_name,
            group_uuid=group_uuid,
            disk_index=disk_index,
            command=cmd,
            privileged=False,
            backoff_limit=backoff_limit,
            active_deadline_seconds=active_deadline_seconds,
        )

    def submit_virt_v2v(
        self,
        *,
        job_name: str,
        group_uuid: str,
        disk_index: int,
        input_path: str,
        output_dir: str,
        backoff_limit: int = 0,
        active_deadline_seconds: int = 12 * 3600,  # virt-v2v can be slow
    ) -> str:
        """Submit a virt-v2v Job that injects virtio drivers (Windows guests)."""
        cmd = [
            "virt-v2v",
            "-i", "disk", input_path,
            "-o", "local",
            "-os", output_dir,
            "-of", "qcow2",
        ]
        return self._submit_job(
            job_name=job_name,
            group_uuid=group_uuid,
            disk_index=disk_index,
            command=cmd,
            privileged=True,        # libguestfs / /dev/kvm
            backoff_limit=backoff_limit,
            active_deadline_seconds=active_deadline_seconds,
        )

    # --- Observation --------------------------------------------------------

    def wait_for_completion(
        self,
        job_name: str,
        *,
        poll_interval_seconds: float = 5.0,
        timeout_seconds: Optional[int] = None,
    ) -> JobOutcome:
        """Block until the Job reaches a terminal state.

        Returns ``JobOutcome``. Raises ``ConversionError(ERR_K8S_JOB_DENIED)``
        on missing-Job or transport errors.
        """
        start = time.monotonic()
        while True:
            try:
                job = self._kv.batch_api.read_namespaced_job_status(
                    name=job_name, namespace=self._namespace,
                    _request_timeout=_K8S_READ_TIMEOUT_SECONDS,  # Audit E9
                )
            except ApiException as e:
                raise ConversionError(
                    "ERR_K8S_JOB_DENIED",
                    f"Could not read Job status {job_name}: {e}",
                    cause=e,
                ) from e

            status = job.status
            if status.succeeded and status.succeeded >= 1:
                return JobOutcome(succeeded=True, failure_reason=None, container_exit_code=0)
            if status.failed and status.failed >= 1:
                reason = self._extract_failure_reason(job_name)
                exit_code = self._extract_exit_code(job_name)
                return JobOutcome(succeeded=False, failure_reason=reason, container_exit_code=exit_code)

            if timeout_seconds is not None and (time.monotonic() - start) > timeout_seconds:
                return JobOutcome(succeeded=False, failure_reason="TimeoutInClient", container_exit_code=None)

            time.sleep(poll_interval_seconds)

    def get_logs(self, job_name: str) -> str:
        """Concatenate stdout/stderr from all pods of the Job (best effort)."""
        try:
            pods = self._kv.core_api.list_namespaced_pod(
                namespace=self._namespace,
                label_selector=f"job-name={job_name}",
            )
        except ApiException as e:
            logger.warning("Could not list pods for job %s: %s", job_name, e)
            return ""

        chunks: list[str] = []
        for pod in pods.items:
            try:
                log = self._kv.core_api.read_namespaced_pod_log(
                    name=pod.metadata.name,
                    namespace=self._namespace,
                    tail_lines=4000,  # cap — full log lives in the cluster
                )
                chunks.append(log or "")
            except ApiException as e:
                chunks.append(f"[error reading log for pod {pod.metadata.name}: {e}]")
        return "\n---\n".join(chunks)

    def delete(self, job_name: str, *, propagate: bool = True) -> None:
        """Delete the Job (and its pods if ``propagate``)."""
        from kubernetes import client as k8s_client
        body = k8s_client.V1DeleteOptions(
            propagation_policy="Foreground" if propagate else "Orphan",
        )
        try:
            self._kv.batch_api.delete_namespaced_job(
                name=job_name, namespace=self._namespace, body=body,
            )
        except ApiException as e:
            if e.status != 404:
                logger.warning("Could not delete Job %s: %s", job_name, e)

    # --- Internals ----------------------------------------------------------

    def _submit_job(
        self,
        *,
        job_name: str,
        group_uuid: str,
        disk_index: int,
        command: list[str],
        privileged: bool,
        backoff_limit: int,
        active_deadline_seconds: int,
    ) -> str:
        manifest = self._build_job_manifest(
            job_name=job_name,
            group_uuid=group_uuid,
            disk_index=disk_index,
            command=command,
            privileged=privileged,
            backoff_limit=backoff_limit,
            active_deadline_seconds=active_deadline_seconds,
        )
        try:
            self._kv.batch_api.create_namespaced_job(
                namespace=self._namespace, body=manifest,
            )
        except ApiException as e:
            raise ConversionError(
                "ERR_K8S_JOB_DENIED",
                f"Cluster refused Job {job_name}: {e}",
                cause=e,
            ) from e
        logger.info("Submitted converter Job %s (disk=%d, privileged=%s)",
                    job_name, disk_index, privileged)
        return job_name

    def _build_job_manifest(
        self,
        *,
        job_name: str,
        group_uuid: str,
        disk_index: int,
        command: list[str],
        privileged: bool,
        backoff_limit: int,
        active_deadline_seconds: int,
    ) -> dict:
        labels = {
            _LABEL_APP: _LABEL_APP_VAL,
            _LABEL_GROUP: group_uuid,
            _LABEL_DISK: str(disk_index),
        }
        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": job_name,
                "namespace": self._namespace,
                "labels": labels,
            },
            "spec": {
                "backoffLimit": backoff_limit,
                "activeDeadlineSeconds": active_deadline_seconds,
                "ttlSecondsAfterFinished": 24 * 3600,
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "restartPolicy": "Never",
                        "containers": [{
                            "name": "converter",
                            "image": self._image,
                            # Always: the *_IMAGE settings point at a rolling
                            # branch tag (shiftwise-backend-worker:<branch>) CD
                            # re-pushes each deploy; IfNotPresent would pin a node
                            # to a stale layer of a moved tag.
                            "imagePullPolicy": "Always",
                            "command": command,
                            "securityContext": {
                                "privileged": privileged,
                            },
                            "volumeMounts": [{
                                "name": "transit",
                                "mountPath": settings.CONVERTER_TRANSIT_ROOT,
                            }],
                            "resources": {
                                "requests": {"cpu": "500m", "memory": "1Gi"},
                                "limits":   {"cpu": "4",    "memory": "8Gi"},
                            },
                        }],
                        "volumes": [{
                            "name": "transit",
                            "persistentVolumeClaim": {"claimName": self._pvc_name},
                        }],
                    },
                },
            },
        }

    def _extract_failure_reason(self, job_name: str) -> Optional[str]:
        # Audit E18 — return the condition's `reason` field ONLY. The
        # free-text `message` field ("Job has reached the specified backoff
        # limit") would poison the exact-match classifier in
        # _classify_k8s_failure, which keys on short reason codes like
        # "BackoffLimitExceeded" / "DeadlineExceeded".
        try:
            job = self._kv.batch_api.read_namespaced_job_status(
                name=job_name, namespace=self._namespace,
                _request_timeout=_K8S_READ_TIMEOUT_SECONDS,  # Audit E9
            )
            for cond in (job.status.conditions or []):
                if cond.type == "Failed" and cond.status == "True":
                    return cond.reason
        except ApiException:
            return None
        return None

    def _extract_exit_code(self, job_name: str) -> Optional[int]:
        try:
            pods = self._kv.core_api.list_namespaced_pod(
                namespace=self._namespace,
                label_selector=f"job-name={job_name}",
            )
        except ApiException:
            return None
        for pod in pods.items:
            for cs in (pod.status.container_statuses or []):
                term = cs.state.terminated if cs.state else None
                if term is not None and term.exit_code is not None:
                    return int(term.exit_code)
        return None
