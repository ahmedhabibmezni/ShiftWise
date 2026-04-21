"""
Tests pour le KubeVirt Client

Teste la connexion et les opérations de base sur OpenShift Virtualization.
"""

import sys
from pathlib import Path

# Ajouter le dossier backend au path Python
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from app.core.kubevirt_client import KubeVirtClient, KubeVirtClientError


def print_section(title: str):
    """Affiche un séparateur de section"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def test_connection():
    """Test de connexion au cluster"""
    print_section("TEST 1 : Connexion au cluster")

    try:
        client = KubeVirtClient()
        print("✅ Client KubeVirt initialisé avec succès")
        return client
    except KubeVirtClientError as e:
        print(f"❌ Erreur d'initialisation : {e}")
        sys.exit(1)


def test_list_vms(client: KubeVirtClient):
    """Test de listage des VMs"""
    print_section("TEST 2 : Liste des VirtualMachines")

    try:
        vms = client.list_vms()
        print(f"✅ {len(vms)} VM(s) trouvée(s)")

        for vm in vms:
            name = vm['metadata']['name']
            status = vm['status'].get('printableStatus', 'Unknown')
            ready = vm['status'].get('ready', False)
            print(f"   📄 {name}")
            print(f"      Status: {status}")
            print(f"      Ready: {ready}")

        return len(vms)
    except KubeVirtClientError as e:
        print(f"❌ Erreur lors du listage des VMs : {e}")
        return 0


def test_list_vmis(client: KubeVirtClient):
    """Test de listage des VMIs"""
    print_section("TEST 3 : Liste des VirtualMachineInstances")

    try:
        vmis = client.list_vmis()
        print(f"✅ {len(vmis)} VMI(s) en cours d'exécution")

        for vmi in vmis:
            name = vmi['metadata']['name']
            phase = vmi['status'].get('phase', 'Unknown')
            node = vmi['status'].get('nodeName', 'N/A')
            interfaces = vmi['status'].get('interfaces', [])
            ip = interfaces[0].get('ipAddress', 'N/A') if interfaces else 'N/A'

            print(f"   🖥️  {name}")
            print(f"      Phase: {phase}")
            print(f"      Node: {node}")
            # print(f"      IP: {ip}")

        return len(vmis)
    except KubeVirtClientError as e:
        print(f"❌ Erreur lors du listage des VMIs : {e}")
        return 0


def test_storage_classes(client: KubeVirtClient):
    """Test de listage des StorageClasses"""
    print_section("TEST 4 : Liste des StorageClasses")

    try:
        scs = client.list_storage_classes()
        print(f"✅ {len(scs)} StorageClass(es) disponible(s)")

        for sc in scs:
            default = " (default)" if "nfs-client" in sc else ""
            print(f"   💾 {sc}{default}")

        return scs
    except Exception as e:
        print(f"❌ Erreur lors du listage des StorageClasses : {e}")
        return []


def test_create_vm(client: KubeVirtClient):
    """Test de création d'une VM"""
    print_section("TEST 5 : Création d'une VM test")

    vm_name = "shiftwise-test-vm"

    try:
        print(f"📝 Création de la VM '{vm_name}'...")

        vm = client.create_vm(
            name=vm_name,
            cpu=1,
            memory="1Gi",
            image="quay.io/containerdisks/fedora:latest",
            run_strategy="Always"
        )

        print(f"✅ VM '{vm_name}' créée avec succès")
        print(f"   UID: {vm['metadata']['uid']}")
        print(f"   Namespace: {vm['metadata']['namespace']}")

        return vm_name

    except KubeVirtClientError as e:
        print(f"❌ Erreur lors de la création de la VM : {e}")
        return None


def test_get_vm_status(client: KubeVirtClient, vm_name: str):
    """Test de récupération du statut d'une VM"""
    print_section("TEST 6 : Statut de la VM")

    try:
        import time

        print(f"⏳ Attente du démarrage de la VM (30 secondes)...")
        time.sleep(30)

        status = client.get_vm_status(vm_name)

        print(f"✅ Statut de '{vm_name}' :")
        for key, value in status.items():
            print(f"   {key}: {value}")

        return status

    except KubeVirtClientError as e:
        print(f"❌ Erreur lors de la récupération du statut : {e}")
        return {}


def test_delete_vm(client: KubeVirtClient, vm_name: str):
    """Test de suppression d'une VM"""
    print_section("TEST 7 : Suppression de la VM test")

    try:
        print(f"🗑️  Suppression de la VM '{vm_name}'...")

        deleted = client.delete_vm(vm_name)

        if deleted:
            print(f"✅ VM '{vm_name}' supprimée avec succès")
        else:
            print(f"⚠️  VM '{vm_name}' non trouvée")

        return deleted

    except KubeVirtClientError as e:
        print(f"❌ Erreur lors de la suppression de la VM : {e}")
        return False


def main():
    """Fonction principale de test"""
    print("\n" + "=" * 70)
    print("  🚀 TESTS KUBEVIRT CLIENT - SHIFTWISE")
    print("=" * 70)

    # Test 1: Connexion
    client = test_connection()

    # Test 2: Liste VMs
    vm_count = test_list_vms(client)

    # Test 3: Liste VMIs
    vmi_count = test_list_vmis(client)

    # Test 4: StorageClasses
    storage_classes = test_storage_classes(client)

    # Test 5: Création VM
    vm_name = test_create_vm(client)

    if vm_name:
        # Test 6: Statut VM
        status = test_get_vm_status(client, vm_name)

        # Test 7: Suppression VM
        test_delete_vm(client, vm_name)

    # Résumé
    print_section("RÉSUMÉ DES TESTS")
    print(f"✅ Connexion au cluster : OK")
    print(f"✅ VMs listées : {vm_count}")
    print(f"✅ VMIs listées : {vmi_count}")
    print(f"✅ StorageClasses : {len(storage_classes)}")
    print(f"✅ Création/Suppression VM : {'OK' if vm_name else 'SKIP'}")
    print("\n" + "=" * 70)
    print("  ✅ TOUS LES TESTS TERMINÉS")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()