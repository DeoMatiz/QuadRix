import subprocess
import sys

# Run pytest
result = subprocess.run(
    [sys.executable, '-m', 'pytest', 'tests/core/test_geometry.py', '-v'],
    capture_output=True, text=True, cwd='H:\\Test\\QuadRix'
)
print('=== STDOUT ===')
print(result.stdout)
print('=== STDERR ===')
print(result.stderr[:2000])
print('=== RETURN CODE ===')
print(result.returncode)