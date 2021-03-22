import os
import stat
import uuid

from amitools.vamos.log import log_lock

from amitools.vamos.astructs import AccessStruct
from amitools.vamos.libstructs import FileLockStruct, DateStampStruct
from .DosProtection import DosProtection
from .AmiTime import *
from .Error import *


class Lock:
    """represent an AmigaOS Lock in vamos"""

    def __init__(self, name, ami_path, sys_path, exclusive=False):
        self.ami_path = ami_path
        self.sys_path = sys_path
        self.name = name
        self.exclusive = exclusive
        self.mem = None
        self.b_addr = 0
        self.vol_addr = 0
        self.key = 0
        self.dirent = None

    def __str__(self):
        addr = 0
        if self.mem is not None:
            addr = self.mem.addr
        return "[Lock:'%s'(ami='%s',sys='%s',key='%s',ex=%d, vol=%d)@%06x=b@%06x]" % (
            self.name,
            self.ami_path,
            self.sys_path,
            self.key,
            self.exclusive,
            self.vol_addr,
            addr,
            self.b_addr,
        )

    def alloc(self, alloc, vol_addr, generate_key):
        self.keygen = generate_key
        self.key = self.keygen(self.sys_path)
        name = "Lock: %s" % self
        self.mem = alloc.alloc_struct(name, FileLockStruct)
        self.mem.access.w_s("fl_Key", self.key)
        self.mem.access.w_s("fl_Volume", vol_addr)
        self.b_addr = self.mem.addr >> 2
        self.vol_addr = vol_addr
        return self.b_addr

    def free(self, alloc):
        alloc.free_struct(self.mem)

    # --- lock ops ---

    def examine_file(self, fib_mem, name, sys_path):
        # name
        name_addr = fib_mem.s_get_addr("fib_FileName")
        # clear 32 name bytes
        mem = fib_mem.mem
        mem.clear_block(name_addr, 32, 0)
        mem.w_cstr(name_addr, name)
        # comment
        comment_addr = fib_mem.s_get_addr("fib_Comment")
        mem.w_cstr(comment_addr, "")
        # create the "inode" information
        key = self.keygen(sys_path)
        fib_mem.w_s("fib_DiskKey", key)
        log_lock.debug("examine key: %08x", key)
        # type
        if os.path.isdir(sys_path):
            dirEntryType = 2
        else:
            dirEntryType = -3
        fib_mem.w_s("fib_DirEntryType", dirEntryType)
        fib_mem.w_s("fib_EntryType", dirEntryType)
        # protection
        prot = DosProtection(0)
        try:
            os_stat = os.stat(sys_path)
            mode = os_stat.st_mode
            if mode & stat.S_IXUSR == 0:
                prot.clr(DosProtection.FIBF_EXECUTE)
            if mode & stat.S_IRUSR == 0:
                prot.clr(DosProtection.FIBF_READ)
            if mode & stat.S_IWUSR == 0:
                prot.clr(DosProtection.FIBF_WRITE)
            log_lock.debug("examine lock: '%s' mode=%03o: prot=%s", name, mode, prot)
        except OSError:
            return ERROR_OBJECT_IN_USE
        fib_mem.w_s("fib_Protection", prot.mask)
        # size
        if os.path.isfile(sys_path):
            size = os.path.getsize(sys_path)
            # limit to 32bit
            if size > 0xFFFFFFFF:
                size = 0xFFFFFFFF
            fib_mem.w_s("fib_Size", size)
            blocks = (size + 511) // 512
            fib_mem.w_s("fib_NumBlocks", blocks)
            log_lock.debug(
                "examine lock: '%s' size=%d, blocks=%d", sys_path, size, blocks
            )
        else:
            fib_mem.w_s("fib_NumBlocks", 1)
            log_lock.debug("examine lock: '%s' no file", sys_path)
        # date (use mtime here)
        date_addr = fib_mem.s_get_addr("fib_Date")
        date = AccessStruct(fib_mem.mem, DateStampStruct, date_addr)
        t = os.path.getmtime(sys_path)
        at = sys_to_ami_time(t)
        date.w_s("ds_Days", at.tday)
        date.w_s("ds_Minute", at.tmin)
        date.w_s("ds_Tick", at.tick)
        # fill in UID/GID
        fib_mem.w_s("fib_OwnerUID", 0)
        fib_mem.w_s("fib_OwnerGID", 0)
        return NO_ERROR

    def examine_lock(self, fib_mem):
        return self.examine_file(fib_mem, self.name, self.sys_path)

    def examine_next(self, fib_mem):
        # start scan
        if self.dirent is None:
            dirEntryType = fib_mem.r_s("fib_DirEntryType")
            if os.path.isdir(self.sys_path):
                self.dirent = os.listdir(self.sys_path)
            else:
                self.dirent = []
            # assume that key stored in given FIB is my own one
            # (otherwise no Examine() on my lock was done before..., aka broken code!)
            fib_key = fib_mem.r_s("fib_DiskKey")
            if fib_key != self.key:
                self.dirent = self._handle_broken_scan(self.dirent, fib_key)

        if len(self.dirent) > 0:
            entry = self.dirent.pop(0)
            e_path = os.path.join(self.sys_path, entry)
            return self.examine_file(fib_mem, entry, e_path)
        else:
            self.dirent = None
            return ERROR_NO_MORE_ENTRIES

    def _handle_broken_scan(self, entries, fib_key):
        log_lock.warning(
            "first ExNext() does not start at Examine()d lock! Broken Code!! lock_key=%08x fib_key=%08x (%s)",
            self.key,
            fib_key,
            self.name,
        )
        # we shrink the dir list to start after the given key
        # and simulate a continued scan as AmigaOS' FFS would do it
        while len(entries) > 0:
            entry = entries.pop(0)
            e_path = os.path.join(self.sys_path, entry)
            e_key = self.keygen(e_path)
            if e_key == fib_key:
                break
        return entries

    def find_volume_node(self, dos_list):
        return self.mem.r_s("fl_Volume")
