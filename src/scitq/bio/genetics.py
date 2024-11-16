import requests
from argparse import Namespace
from typing import Optional, List, Dict, Tuple, Union
import subprocess
import io
import csv
import re
from scitq.fetch import list_content, FASTQ_PARITY
import statistics
import math
import copy

DEPTH_REGEXP=re.compile(r"(?P<pair1>[12]x)?(?P<core>\d+[kmg]?)(?P<pair2>x[12])?")

class BioException(Exception):
    pass

def ena_get_samples(bioproject:str, library_layout:Optional[str]=None, library_strategy:Optional[str]=None) -> Dict[str,List[Namespace]]:
    """Get a list of runs grouped by sample, optionally filtered by library_layout (PAIRED/SINGLE for instance) 
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

def sra_get_samples(bioproject:str, library_layout:Optional[str]=None, library_strategy:Optional[str]=None) -> Dict[str,List[Namespace]]:
    """Get a list of runs grouped by sample, optionally filtered by library_layout (paired/single for instance) 
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
    
    if len(p.stdout.split())==0:
        raise BioException(f'No such bioproject {bioproject}')

    header_line,body = p.stdout.split(maxsplit=1)

    # fixing SRA headers to make them more consistent with ENA and python style
    new_style_headers = []
    for header in header_line.split(','):
        words=[word[:-1].lower() if word.endswith('_') else word.lower() for word in re.findall('[A-Z]?[^A-Z]+|[A-Z]{2,3}', header)]
        new_style_headers.append('_'.join(words) if words else header) 

    output=io.StringIO(f"{','.join(new_style_headers)}\n{body}")
    samples = {}
    for item in csv.DictReader(output, delimiter=','):
        run=Namespace(**item)
        if library_strategy and run.library_strategy!=library_strategy:
            continue
        if library_layout and run.library_layout!=library_layout:
            continue
        run.uri=f'run+fastq@sra://{run.run}'
        run.sample_accession = run.bio_sample
        if run.bio_sample not in samples:
            samples[run.bio_sample]=[run]
        else:
            samples[run.bio_sample].append(run)
    return samples

def count(items: List[str], ending: str) -> int:
    """Count how many items end with ending"""
    return len([item for item in items if item.endswith(ending)])

def uri_get_samples(uri: str, ending: str='.fastq.gz', alternate_endings: List[str]=['.fastq','.fq.gz','.fq']) -> Dict[str,List[Namespace]]:
    """Get a list of runs grouped by sample organized within the folder uri,
     this function tries to guess the organization of files, grouped by folder or common prefix, 
     it also tries to infer some info like library_layout"""
    samples = {}
    project_files = [file for file in list_content(uri) if file.rel_name.endswith(ending)]
    candidate_endings=iter(alternate_endings)
    try:
        while len(project_files)==0:
            ending = next(candidate_endings)
            project_files = [file for file in list_content(uri) if file.rel_name.endswith(ending)]
    except StopIteration:
        raise BioException(f'{uri} does not seems to contains sample files')
    
    # try grouped by folder
    for file in project_files:
        sample = file.name.split('/')[-2]
        if sample not in samples:
            samples[sample]=[]
        samples[sample].append(file.name)
    
    folder_grouped = True
    if len(project_files)/len(samples) > 3:
        folder_grouped = False
    else:
        file_topology = [len(files) for files in samples.values()]
        if len(file_topology)>1 and statistics.stdev(file_topology)>statistics.mean(file_topology):
            folder_grouped = False
    
    # try to group by common part 
    if not folder_grouped:
        group_by_common_prefix = False
        common_prefix_len = math.floor(statistics.mean([len(file.rel_name) for file in project_files])) - len(ending)
        while common_prefix_len>0:
            candidate_samples = {}
            for file in project_files:
                sample = file.rel_name[:common_prefix_len]
                if sample not in candidate_samples:
                    candidate_samples[sample]=[]
                candidate_samples[sample].append(file.name)
            if len(project_files)/len(candidate_samples)<1.5:
                common_prefix_len-=1
                continue
            file_topology = [len(files) for files in candidate_samples.values()]
            if len(file_topology)>1 and statistics.stdev(file_topology)>statistics.mean(file_topology):
                common_prefix_len-=1
                continue
            group_by_common_prefix = True
            break
        if group_by_common_prefix:
            print(f'Samples seem to be grouped by common prefix of length {common_prefix_len}')
            samples = candidate_samples
        else:
            samples={}
            common_prefix_len = math.floor(statistics.mean([len(file.rel_name) for file in project_files])) - len(ending)
            for file in project_files:
                sample = file.rel_name[:common_prefix_len]
                if sample not in samples:
                    samples[sample]=[]
                samples[sample].append(file.name)
            print('Could not find any grouping possibility')
    else:
        print('Samples seem to be grouped by folder')

    final_samples = {}
    for sample, files in samples.items():
        if len(files)%2==0 and count(files,f'2{ending}')==count(files,f'1{ending}'):
            library_layout = 'PAIRED'
        else:
            library_layout = 'SINGLE'
        final_samples[sample] = [Namespace(sample_accession=sample, uri=file, library_layout=library_layout) for file in files]
    return final_samples

def find_library_layout(samples: Dict[str,List[Namespace]]) -> str:
    """Look for the dominant library_layout in a group of sample"""
    paired=single=0
    for sample,runs in samples.items():
        single_likeliness=0
        for run in runs:
            if run.library_layout=='SINGLE':
                single_likeliness+=1
            elif run.library_layout=='PAIRED':
                paired+=1
                break
        else:
            if single_likeliness>0:
                single+=1
    if single==paired or (single==0 and paired==0):
        raise BioException(f'Cannot decide: paired vote {paired} vs single vote {single}')
    library_layout = 'PAIRED' if paired>single else 'SINGLE'
    return library_layout

def filter_by_layout(samples: Dict[str,List[Namespace]], paired: bool, use_only_r1: bool=True) -> Dict[str,List[Namespace]]:
    """A simple filter by layout (e.g. PAIRED/SINGLE) wiht a little subtelty: when filtering for SINGLE,
    there are two option for PAIRED samples: the most likely option is not discard the sample but to remove half the reads
    (option use_only_r1 - note that this option is only effective when filtering for SINGLE, e.g. if 'paired' is set to False)
    If use_only_r1 is set to False, then PAIRED samples are simply discarded, keeping only SINGLE.
    """
    filtered_samples = {}
    if paired:
        for sample,runs in samples.items():
            runs = [run for run in runs if run.library_layout=='PAIRED']
            if runs:
                filtered_samples[sample]=runs
    else:
        if use_only_r1:
            for sample,runs in samples.items():
                filtered_runs = []
                for run in runs:
                    if run.uri.startswith('run+fastq'):
                        new_run = copy.deepcopy(run)
                        if new_run.library_layout=='PAIRED':
                            new_run.uri=new_run.uri.replace('run+fastq','run+fastq@filter_r1')
                        filtered_runs.append(new_run)
                    elif run.library_layout=='PAIRED':
                        m=FASTQ_PARITY.match(run.uri)
                        if not(m) or m.groups()[0]=='1':
                            filtered_runs.append(run)
                    else:
                        filtered_runs.append(run)
                if filtered_runs:
                    filtered_samples[sample]=filtered_runs
        else:
            for sample,runs in samples.items():
                runs = [run for run in runs if run.library_layout=='SINGLE']
            if runs:
                filtered_samples[sample]=runs
    return filtered_samples
class Depth:
    """A simple object providing minimal information of the type of sequencing"""
    
    def __init__(self, read_number: int, paired: Optional[bool]=None):
        self.read_number = read_number
        self.paired = paired
        self.single = not paired

    def __repr__(self):
        return f'Depth({self.read_number}{f",paired={self.paired}" if self.paired is not None else ""})'
    
    def to_tuple(self) -> Tuple[int,Union[bool,None]]:
        """Convert object to a tuple of (read_number, paired) for convenient attribution to disctinct variables"""
        return (self.read_number, self.paired)

    @property
    def total_read_number(self):
        return self.read_number*2 if self.paired else self.read_number

def filter_by(samples: Dict[str,List[Namespace]], **filters: any) -> Dict[str,List[Namespace]]:
    """A simple filter by multiple criteria find in the different objects contained in the Dict samples
    typically: filter_by(samples, library_strategy='WGS')
    """
    filtered_samples = {}
    for sample, runs in samples.items():
        filtered_runs = []
        for run in runs:
            for attribute,value in filters.items():
                if getattr(run, attribute, None)!=value:
                    break
            else:
                filtered_runs.append(run)
        if filtered_runs:
            filtered_samples[sample]=filtered_runs
    return filtered_samples

def user_friendly_depth(depth_string: str) -> Depth:
    """It is commun to specify depth as a string like 2x20M for 20000000 of pair of reads or 100Kx1 for 100000 single reads
    return a depth object containing read_number
    """
    m = DEPTH_REGEXP.match(depth_string.lower())

    if not m:
        raise BioException(f'{depth_string} does not looks like a correct depth string')
    
    m = Namespace(**m.groupdict())
    return Depth(read_number=int(m.core.replace('k','000').replace('m','000000').replace('g','000000000')),
                 paired=m.pair1=="2x" if m.pair1 is not None else m.pair2=="x2" if m.pair2 is not None else None)