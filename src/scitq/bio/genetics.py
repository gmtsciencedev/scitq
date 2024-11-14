import requests
from argparse import Namespace
from typing import Optional, List
import subprocess
import io
import csv

class BioException(Exception):
    pass

def ena_get_samples(bioproject:str, library_layout:Optional[str]=None, library_strategy:Optional[str]=None):
    """Get a list of runs grouped by sample, optionally filtered by library_layout (PAIRED/UNPAIRED for instance) 
    and or by library_strategy (WGS/AMPLICON for instance)
    The run objects listed have a uri attribute that can conveniently be used as input in scitq tasks"""
    ena_query=f"https://www.ebi.ac.uk/ena/portal/api/filereport?accession={bioproject}&\
result=read_run&fields=all&format=json&download=true&limit=0"
    samples = {}
    for item in requests.get(ena_query).json():
        run = Namespace(**item)
        if library_strategy and run.library_strategy!=library_strategy:
            continue
        if library_layout and run.library_layout!=library_layout:
            continue
        run.uri=f'run+fastq://{run.run_accession}'
        if run.sample_accession not in samples:
            samples[run.sample_accession]=[run]
        else:
            samples[run.sample_accession].append(run)
    return samples

def sra_get_samples(bioproject:str, LibraryLayout:Optional[str]=None, LibraryStrategy:Optional[str]=None):
    """Get a list of runs grouped by sample, optionally filtered by library_layout (paired/unpaired for instance) 
    and or by library_strategy (WGS/amplicon for instance)
    The run objects listed have a uri attribute that can conveniently be used as input in scitq tasks"""
    try:
        p=subprocess.run(f'''docker run --rm -it ncbi/edirect sh -c "esearch -db sra -query '{bioproject}[bioproject]' | efetch -format runinfo"''',
                                     shell=True, check=True, capture_output=True, encoding='UTF-8')
    except subprocess.CalledProcessError as error:
        if error.returncode==127:
            raise BioException('docker command was not found and is required for sra_get_samples')
        else:
            raise error
            
    output=io.StringIO(p.stdout)
    samples = {}
    for item in csv.DictReader(output, delimiter=','):
        run=Namespace(**item)
        if LibraryStrategy and run.LibraryStrategy!=LibraryStrategy:
            continue
        if LibraryLayout and run.LibraryLayout!=LibraryLayout:
            continue
        run.uri=f'run+fastq@sra://{run.Run}'
        if run.BioSample not in samples:
            samples[run.BioSample]=[run]
        else:
            samples[run.BioSample].append(run)
    return samples