import requests
from argparse import Namespace
from typing import Optional, List, Dict, Tuple, Union
import subprocess
import io
import csv
import re

DEPTH_REGEXP=re.compile(r"(?P<pair1>[12]x)?(?P<core>\d+[kmg]?)(?P<pair2>x[12])?")

class BioException(Exception):
    pass

def ena_get_samples(bioproject:str, library_layout:Optional[str]=None, library_strategy:Optional[str]=None) -> Dict[str,List[Namespace]]:
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

def sra_get_samples(bioproject:str, LibraryLayout:Optional[str]=None, LibraryStrategy:Optional[str]=None) -> Dict[str,List[Namespace]]:
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

class Depth:
    """A simple object providing minimal information of the type of sequencing"""
    
    def __init__(self, read_number: int, paired: Optional[bool]=None):
        self.read_number = read_number
        self.paired = paired

    def __repr__(self):
        return f'Depth({self.read_number}{f",paired={self.paired}" if self.paired is not None else ""})'
    
    def to_tuple(self) -> Tuple[int,Union[bool,None]]:
        """Convert object to a tuple of (read_number, paired) for convenient attribution to disctinct variables"""
        return (self.read_number, self.paired)


def user_friendly_depth(depth_string: str) -> Depth:
    """It is commun to specify depth as a string like 2x20M for 20000000 of pair of reads or 100Kx1 for 100000 unpaired reads
    return a depth object containing read_number
    """
    m = DEPTH_REGEXP.match(depth_string.lower())

    if not m:
        raise BioException(f'{depth_string} does not looks like a correct depth string')
    
    m = Namespace(**m.groupdict())
    return Depth(read_number=int(m.core.replace('k','000').replace('m','000000').replace('g','000000000')),
                 paired=m.pair1=="2x" if m.pair1 is not None else m.pair2=="x2" if m.pair2 is not None else None)