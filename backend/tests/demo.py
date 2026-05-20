import sys
from pathlib import Path

# Ajouter le dossier backend au path Python
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from app.core.kubevirt_client import KubeVirtClient

# Initialisation
print("🔧 Initialisation du client...")
client = KubeVirtClient()

# Lister les VMs existantes
print("\n📋 VMs actuelles :")
vms = client.list_vms()
for vm in vms:
    name = vm['metadata']['name']
    status = vm['status'].get('printableStatus', 'Unknown')
    print(f"   - {name}: {status}")

# Créer une nouvelle VM
print("\n🚀 Création d'une VM de démonstration...")
vm = client.create_vm(
    name="demo-shiftwise-vm",
    cpu=1,
    memory="1Gi",
    image="quay.io/containerdisks/fedora:latest"
)
print(f"✅ VM '{vm['metadata']['name']}' créée avec succès")

# Attendre quelques secondes
import time
print("\n⏳ Démarrage de la VM...")
time.sleep(17)

# Vérifier le statut
status = client.get_vm_status("demo-shiftwise-vm")
print(f"\n📊 Statut de la VM :")
for key, value in status.items():
    print(f"   {key}: {value}")

# Nettoyer
print("\n🗑️  Suppression de la VM de démo...")
client.delete_vm("demo-shiftwise-vm")
print("✅ VM supprimée")
