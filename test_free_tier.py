import sys
import os

from deven.utils.license_manager import LicenseManager

print("[*] Testing 14 buses (IEEE 14):")
v14, msg14, _ = LicenseManager.verify_license(study_code="LFA", num_buses=14)
print(f"    Allowed: {v14} | Message: {msg14}")

print("\n[*] Testing 100 buses:")
v100, msg100, _ = LicenseManager.verify_license(study_code="LFA", num_buses=100)
print(f"    Allowed: {v100} | Message: {msg100}")

print("\n[*] Testing 101 buses:")
v101, msg101, _ = LicenseManager.verify_license(study_code="LFA", num_buses=101)
print(f"    Allowed: {v101} | Message: {msg101}")

print("\n[*] Testing 102 buses (exceeds free tier limit):")
v102, msg102, _ = LicenseManager.verify_license(study_code="LFA", num_buses=102)
print(f"    Allowed: {v102}")
