#! python3
'''
main method along with argument parsing functions
'''
# ************************************************************
# Imports
# ************************************************************
import sys

import argparse

from pathlib import Path

import os

from support.utils import dbgmsg, exitfunction

from db.wsuse_db import construct_tables

from ProcessPools import DBMgr, ExtractMgr, CleanMgr, SymMgr

import globs

# ************************************************************
# Requirements:
#     Minimal Python Version: 3.6
#     SQLite
#     pefile
#     Windows SDK/WDK (expand.exe and symcheck.exe)

# Extraction tools:
#     expand.exe

# Description:
# takes WSUS updates files and extracts PE files from them in order to obtain the symbols
# files. Also stores various metadata on update, PE, and pdb files in SQLITE database
# so that information is accessible.

# more future updates:
# Handle all language version for patches/binaries/pdb.
# If using expand.exe and symhck.exe, VERIFY that the found binaries are signed
# by Microsoft (i.e., check root cert).
# Enable functionality for single cab file.


# Two methods:
# * use externals tools
# * use open source tools

# HOW-TO-USE:
# 1) WSUSContent directory  <---- first
# ************************************************************

# Verify Python version
if sys.version_info[0] < 3 and sys.version_info[1] >= 6:
    sys.exit("This script requires at least Python version 3.6")


def displayhelp(parserh):
    '''
    displays help prompt
    '''
    parserh.print_help()


def parsecommandline(parser):
    '''
    parses arguments given to commandline
    '''
    parser.add_argument(
        "-f", "--file", help="Path to single patch file. Must be given -x or --extract as well.")
    parser.add_argument(
        "-x", "--extract", action='store_true')
    parser.add_argument(
        "-c", "--createdbonly", action='store_true')
    parser.add_argument(
        "-p", "--patchpath", help="Path to location where Windows updates " +
        "(CAB/MSU) are stored. Must be given -x or --extract as well.")
    parser.add_argument(
        "-pd", "--patchdest",
        help="An optional destination where extracted PE files will be stored",
        nargs="?",
        type=str,
        default="extractedPatches")
    parser.add_argument(
        "-gs", "--getsymbols",
        help="Create/Update symbol DB information for extracted PE files " +
        "(requires --createdbonly and cannot be used with any other \"get\" option)",
        action='store_true')
    parser.add_argument(
        "-gp", "--getpatches",
        help="Create/Update patches DB information for symbol files " +
        "(requires --createdbonly and cannot be used with any other \"get\" option)",
        action='store_true')
    parser.add_argument(
        "-gu", "--getupdates",
        help="Create/Update update file DB information for update files " +
        "(requires --createdbonly and cannot be used with any other \"get\" option)",
        action='store_true')
    parser.add_argument(
        "-sl", "--symlocal",
        help=("Path to location where local symbols are be stored. "
              "Used only to populate the database and move symbols to "
              "specified location."),
        action='store_true')
    parser.add_argument(
        "-ss", "--symbolserver",
        help="UNC Path to desired Symbol server. Defaults to "
        "https://msdl.microsoft.com/download/symbols. If symlocal is"
        " specified a local directory is used",
        nargs="?",
        type=str,
        default="https://msdl.microsoft.com/download/symbols"
        )
    parser.add_argument(
        "-sp", "--symdestpath",
        help="Path to location where obtained symbols will be stored",
        nargs="?",
        type=str,
        default="updatefilesymbols")
    parser.add_argument(
        "-m", "--module",
        help="specify module to invoke",
        nargs="?",
        type=str,
        default="updatefilesymbols")
    parser.add_argument(
        "-v", "--verbose",
        action='store_true',
        help="turn verbose output on or off"
    )

    if len(sys.argv) == 1:
        displayhelp(parser)
        exitfunction()

    return parser.parse_args()


def checkdirectoryexist(direxist):
    '''
    Check if directory exists
    '''
    result = False
    if not os.path.isdir(("%r"%direxist)[1:-1]):
        try:
            os.mkdir(direxist)
            result = True
        except FileExistsError as ferror:
            dbgmsg("[MAIN] {-} unable to make symbol destination directory " + \
                    str(ferror.winerror) + " " +  str(ferror.strerror))
    dbgmsg("[MAIN] Directory ("+ direxist + ") results were " + str(int(result)))
    return result

if __name__ == "__main__":

    import time

    PARSER = argparse.ArgumentParser()
    ARGS = parsecommandline(PARSER)

    # ************************************************************
    # times
    # ************************************************************
    ELPASED_EXTRACT = 0
    ELPASED_CHECKBIN = 0
    ELPASED_GETSYM = 0
    START_TIME = 0
    EXTRACTMIN = 0
    CHECKBINMIN = 0
    GETSYMMIN = 0

    # set verbose output on or off, this is apparently the Python approved way to do this
    if ARGS.verbose:
        import ModVerbosity

    # ARGS.file currently not in use, way to extract single cab not yet developed
    if ARGS.extract and (ARGS.patchpath or ARGS.file):
        # Clean-slate (first time) / Continous use or reconstruct DB
        # (internet or no internet)
        print("Extracting updates and retrieving symbols")

        patchdest = None

        if ARGS.patchdest:
            checkdirectoryexist(ARGS.patchdest)
        
        patchdest = ARGS.patchdest.rstrip('\\')

        if ARGS.symdestpath:
            checkdirectoryexist(ARGS.symdestpath)

        if not construct_tables(globs.DBCONN):
            dbgmsg("[MAIN] Problem creating DB tables")
            globs.DBCONN.close()
            exit()

        DB = DBMgr(patchdest, globs.DBCONN)
        SYM = PATCH = UPDATE = None

        print("Examining " + ARGS.patchpath)

        print("Ensuring only PE files are present in " + ARGS.patchpath)

        LOCAL = False
        LOCALDBC = False

        if ARGS.symlocal:
            print("Using local path for symbols....")
            LOCAL = True

        if ARGS.createdbonly:
            print("Creating local DB only....")
            LOCALDBC = True

        print("Using symbol server (" + ARGS.symbolserver + ") to store at (" + \
              ARGS.symdestpath + ")")

        # number of processes spawned will be equal to the number of CPUs in the system
        CPUS = os.cpu_count()

        SYM = SymMgr(CPUS, ARGS.symbolserver, ARGS.symdestpath, DB, LOCAL)
        PATCH = CleanMgr(CPUS, SYM, DB)
        UPDATE = ExtractMgr(ARGS.patchpath, patchdest, CPUS, PATCH, DB, LOCALDBC)

        START_TIME = time.time()
        DB.start()
        SYM.start()
        PATCH.start()
        UPDATE.start()

        UPDATE.join()
        ELPASED_EXTRACT = time.time() - START_TIME
        EXTRACTMIN = ELPASED_EXTRACT / 60
        print(("Time to extract ({}),").format(EXTRACTMIN))
        PATCH.join()
        ELPASED_CHECKBIN = time.time() - START_TIME
        CHECKBINMIN = ELPASED_CHECKBIN / 60
        print(("Time to check binaries ({}),").format(CHECKBINMIN))
        SYM.join()
        ELPASED_GETSYM = time.time() - START_TIME
        GETSYMMIN = ELPASED_GETSYM / 60
        print(("Time to find symbols ({}),").format(GETSYMMIN))
        DB.join()
        TOTAL_ELAPSED = time.time() - START_TIME
        TOTALMIN = TOTAL_ELAPSED / 60
        print(("Total time including database insertion ({})").format(TOTALMIN))

        print("Updates Completed, check WSUS_Update_data.db for symbols, "
              "update metadata, binaries")
    elif ARGS.createdbonly and ARGS.patchpath and ARGS.symbolserver and ARGS.patchdest:
        # Create/Update DB only from Update files, extracted files,
        # and downloaded symbols

        # Only create the SymbolFiles Table
        if ARGS.getsymbols:
            if not construct_tables(globs.DBCONN):
                dbgmsg("[MAIN] Problem creating DB tables")
                globs.DBCONN.close()
                exit()

            # (Re)create the Symbol table / retrieve symbols only
            DB = DBMgr(globs.DBCONN)
            SYM = None

            print("Only retrieving symbols")
            LOCAL = False
            if ARGS.symlocal:
                LOCAL = True

            SYM = SymMgr(4, ARGS.symbolserver, ARGS.symdestpath, DB, LOCAL)

            DB.start()
            SYM.start()

            for root, dummy, files in os.walk(ARGS.patchdest):
                for item in files:
                    job = Path(os.path.join(root + "\\" + item)).resolve()
                    SYM.receivejobset(job)

            SYM.donesig()
            SYM.join()

            for i in range(0, 2):
                DB.donesig()
            DB.join()

            print("retrieving of symbols complete. Check WSUS_Update_data.db for symbols")
        # Only create the PatchedFiles Table
        elif ARGS.getpatches:
            if not construct_tables(globs.DBCONN):
                dbgmsg("[MAIN] Problem creating DB tables")
                globs.DBCONN.close()
                exit()

            # (Re)create the PatchFile table / retrieve patches only
            DB = DBMgr(globs.DBCONN)
            CLEAN = None

            print("Only retrieving patches")

            CLEAN = CleanMgr(1, None, DB)

            DB.start()
            CLEAN.start()

            for root, folders, dummy in os.walk(ARGS.patchpath):
                for item in folders:
                    job = Path(os.path.join(root + "\\" + item)).resolve()
                    CLEAN.receivejobset(job)

            CLEAN.donesig()
            CLEAN.join()

            for i in range(0, 2):
                DB.donesig()
            DB.join()

            print("retrieving of patches complete. Check WSUS_Update_data.db for patch files")
        # Only create the UpdateFiles Table
        elif ARGS.getupdates:
            if not construct_tables(globs.DBCONN):
                dbgmsg("[MAIN] Problem creating DB tables")
                globs.DBCONN.close()
                exit()

            # (Re)create the UpdateFiles table / retrieve updates only
            DB = DBMgr(globs.DBCONN)
            UPD = None

            print("Only retrieving updates")

            UPD = ExtractMgr(ARGS.patchpath, ARGS.patchdest, 4, None, DB, True)

            DB.start()
            UPD.start()
            UPD.join()

            for i in range(0, 2):
                DB.donesig()
            DB.join()

            print("retrieving of Updates complete. Check WSUS_Update_data.db for update files")
    else:
        print("Invalid option -- view -h")

    print(("Time to extract ({})," +
           "Time to checkbin ({})," +
           "Time to get symbols ({})").format(EXTRACTMIN, CHECKBINMIN,
                                              GETSYMMIN))

    globs.DBCONN.close()
