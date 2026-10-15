"""Prepare deployment inputs; no secrets printed or sent over the network."""
import base64,json,secrets
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
root=Path(__file__).resolve().parents[2]
folder=root/'private';folder.mkdir(exist_ok=True)
keypath=folder/'ebay-notifications.pem'
if keypath.exists():
 key=serialization.load_pem_private_key(keypath.read_bytes(),password=None)
else:
 key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
 keypath.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
def b64int(n):return base64.urlsafe_b64encode(n.to_bytes((n.bit_length()+7)//8,'big')).decode().rstrip('=')
numbers=key.public_key().public_numbers()
path=folder/'ebay-notifications-config.json'
if not path.exists():
 path.write_text(json.dumps({'PUBLIC_KEY_JWK':json.dumps({'kty':'RSA','n':b64int(numbers.n),'e':b64int(numbers.e),'alg':'RSA-OAEP-256','ext':True}), 'VERIFICATION_TOKEN':secrets.token_urlsafe(36),'POLL_TOKEN':secrets.token_urlsafe(48)},indent=2),encoding='utf-8')
print('Private encryption key and deployment inputs prepared; values not printed.')
