"""Resolve a module+offset from a Windows crash record into a function name and source
line, using dbghelp straight from the PDB.

Why this exists: the WER record for the 10:44 crash says only
`s3engine.dll + 0x14a32, exception 0xc0000005`, and the engine wrote no log line for that
run -- the process died before the first flush. Two of the three artefacts a crash needs
are gone; the PDB is the third, and it is 97 MB of it sitting beside the DLL that crashed.

No debugger is installed on this box, so this drives dbghelp through ctypes. Only the
name is read out of SYMBOL_INFO (and the line from SymGetLineFromAddr64), which keeps the
struct-layout risk small: SizeOfStruct on x64 is the documented 88, and the name is the
NUL-terminated bytes that follow it.

Usage: python pdb_lookup.py <pdb> <rva-in-hex>
"""
import ctypes
import struct
import sys

dbghelp = ctypes.WinDLL("dbghelp.dll")
kernel32 = ctypes.WinDLL("kernel32.dll")

SYMOPT_UNDNAME = 0x00000002
SYMOPT_LOAD_LINES = 0x00000010
hproc = kernel32.GetCurrentProcess()

dbghelp.SymSetOptions(SYMOPT_UNDNAME | SYMOPT_LOAD_LINES)
dbghelp.SymInitialize.restype = ctypes.c_bool
dbghelp.SymInitialize.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_bool]

pdb_path = sys.argv[1]
dll_path = sys.argv[3] if len(sys.argv) > 3 else pdb_path.rsplit(".", 1)[0] + ".dll"

if not dbghelp.SymInitialize(hproc, pdb_path.rsplit("\\", 1)[0].encode(), False):
    sys.exit("SymInitialize failed, gle=%d" % kernel32.GetLastError())

# SymFromAddr resolves addresses in a LOADED module. The process that crashed is gone, so
# the DLL is mapped on paper at its own preferred base -- pefile reads that and the image
# size out of the headers, and SymLoadModuleEx points dbghelp at the matching PDB. Every
# address queried afterwards is preferred-base + the RVA from the crash record.
import pefile
pe = pefile.PE(dll_path)
base = pe.OPTIONAL_HEADER.ImageBase
imgsize = pe.OPTIONAL_HEADER.SizeOfImage
dbghelp.SymLoadModuleEx.restype = ctypes.c_uint64
dbghelp.SymLoadModuleEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p,
                                    ctypes.c_char_p, ctypes.c_uint64, ctypes.c_ulong,
                                    ctypes.c_void_p, ctypes.c_ulong]
if not dbghelp.SymLoadModuleEx(hproc, None, dll_path.encode(), None, base, imgsize, None, 0):
    sys.exit("SymLoadModuleEx failed, gle=%d" % kernel32.GetLastError())
print("module : %s  preferred base 0x%x  image 0x%x" % (dll_path.rsplit("\\", 1)[-1], base, imgsize))

# ---- symbol name -----------------------------------------------------------------
SIZEOF_STRUCT = 88          # x64 SYMBOL_INFO without the trailing name buffer
buf = ctypes.create_string_buffer(2048)
struct.pack_into("I", buf, 0, SIZEOF_STRUCT)      # SizeOfStruct
disp = ctypes.c_uint64(0)

dbghelp.SymFromAddr.restype = ctypes.c_bool
dbghelp.SymFromAddr.argtypes = [ctypes.c_void_p, ctypes.c_uint64,
                                ctypes.POINTER(ctypes.c_uint64), ctypes.c_char_p]
addr = base + int(sys.argv[2], 16)
if dbghelp.SymFromAddr(hproc, addr, ctypes.byref(disp), buf):
    raw = buf[SIZEOF_STRUCT:].split(b"\x00", 1)[0]
    print("symbol : %s + 0x%x" % (raw.decode("utf-8", "replace"), disp.value))
else:
    print("symbol : not found (gle=%d)" % kernel32.GetLastError())

# ---- source line -----------------------------------------------------------------
class IMAGEHLP_LINE64(ctypes.Structure):
    _fields_ = [("SizeOfStruct", ctypes.c_uint32),
                ("Key", ctypes.c_void_p),
                ("LineNumber", ctypes.c_uint32),
                ("FileName", ctypes.c_char_p),
                ("Address", ctypes.c_uint64)]

class WIN32_FIND_DATA(ctypes.Structure):
    _fields_ = [("c", ctypes.c_byte * 600)]

line = IMAGEHLP_LINE64()
line.SizeOfStruct = ctypes.sizeof(IMAGEHLP_LINE64)
found = ctypes.c_uint32(0)
dbghelp.SymGetLineFromAddr64.restype = ctypes.c_bool
dbghelp.SymGetLineFromAddr64.argtypes = [ctypes.c_void_p, ctypes.c_uint64,
                                         ctypes.POINTER(ctypes.c_uint32),
                                         ctypes.POINTER(IMAGEHLP_LINE64)]
if dbghelp.SymGetLineFromAddr64(hproc, addr, ctypes.byref(found), ctypes.byref(line)):
    print("source : %s:%d" % (line.FileName.decode("utf-8", "replace"), line.LineNumber))
else:
    print("source : no line info (gle=%d)" % kernel32.GetLastError())

dbghelp.SymCleanup(hproc)
