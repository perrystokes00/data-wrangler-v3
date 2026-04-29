import hashlib
val = "JAY BERGMAN OIL CO"  # whatever the result is
print(hashlib.sha1(val.upper().encode('utf-16-le')).hexdigest().upper())
