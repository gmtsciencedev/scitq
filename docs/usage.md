# Usage

## Task definition 
As said in the introduction, scitq is about distributing tasks, but what a task is has not been clearly defined. In the [quick start](../#quick-start), the proposed task is `echo 'Hello world!'`, that is a simple command, with its parameter(s), which make it pretty much what you want, but with some restrictions that are not explicit in that definition. 

This is the only theoretical part of the chapter. If you want to jump into usage, go directly to the next section: [Programming a task](#queuing-a-task)

### self contained
First, the task should be self-contained, it should rely on a limited input known before launch time, and depends on a reasonable amount of (read-only shared) resources. There are two specific mechanics to answer both points in scitq (respectively [input](#input--i) and [resource](#resource--r)). Be aware that scitq is not suited to interdependent tasks: there is a third mechanism to take care of results collection ([output](#output--o)), but this is not accessible by the other tasks that were programmed before the producing task ended.

### atomic
Second, the task should be atomic, that is complete after a certain computation time on its own with a return code, expressed with the Unix paradigm, 0 if it is OK, some other number if it is not. 

It excludes unix services and other never-ending tasks, or task whose ending status is always 0 (usually poorly coded programs) or the other way around. In fact, it is not strictly impossible to use such tasks but you will not be able to use the error treatment capability of scitq. It also excludes tasks with user interaction.


### predictible (in terms of requirements: cpu, mem, disk)
That's the last one but not the least. Some programs are extremely nice (like pigz), they let you choose how many threads you will use and consume a reasonable amount of memory, plus they are very constant in their needs (you do not have to monitor them for hours to guess how they will behave). Some programs are very bad in that regard, they tend to be very variable in their needs during their computation time and they offer little or no control over it. They are not impossible to work with but will give you a hard time.

scitq will not help you to know what your needs are so the basic rule is to run one task completely either with a resource surveying program (like Zabbix, free and excellent), or simply using top and watching.



## Queuing a task

!!! note
    be careful that if you have some enabled worker (likely in the default batch, see below) not in pause, then queued tasks will get executed at once. The way to avoid that is to place the queued task in a specific batch, which is the first option explained.

This requires the utility `scitq-launch`. It has a long list of options but none is mandatory, we will cover them here:

In its most basic usage, if your command executed outside of scitq would look like:
```bash
mycommand --myoption myarg
```

Then to queue this task in scitq, simply:
```bash
scitq-launch mycommand --myoption myarg
```

### batch (-b)

This will ask any available worker in the default batch to execute this command. Batch is used by scitq to separate things. Each batch is just a name (a character string, generally short something like `assembly_genome_ecoli`), that is associated with one or several tasks and one or several workers. Each batch is completely independent of another, so a task associated with a certain batch is invisible to workers associated with another. When a task or a worker is created without a batch, it belongs to the default batch. While it is fine if you work alone and you do one list of tasks at a time, in a team, it is advised never to use the default batch. That's what we'll do with `-b` option:

```bash
scitq-launch -b mybatch mycommand --myoption myarg
```

### docker (-d)

One of the tricky things with delegating the execution of a command is the notion of context. The context of your shell (maybe with a conda environment) is very specific, and is not the context of execution of the worker (remember the worker run as root). Especially when the worker is not on the same server. Containers and docker more specifically offer a very fine solution to that issue, and we will consider you have a *public* docker that suits your needs, so that you would have launched your command like that:

```bash
docker run mypublicdocker mycommand --myoption myarg
```

Then queuing would be simply like this (we did not repeat the above option `-b mybatch` to make things very simple, but it should be added):
```bash
scitq-launch -d mypublicdocker mycommand --myoption myarg
```

Then generally with docker, you mount volume(s) with docker -v option so that you can access some external files to the docker and recover some results file. Here scitq will automatically propose several mounts or mapping automatically. There are 4 of them:

- /data : it is used in [NFS](specific.md#using-nfs) context. If you activated NFS support in scitq then /data will be available in /data in the docker context (it is the only mount available also out of docker context),
- /input : we will cover that just after with [input](#input--i) option, if you specify any input option, the files will be made available to your task in that folder,
- /resource : it is very much like /input, but related to [resource](#resource--r) options. The difference with input is that resources are shared between tasks.
- /output : it is linked to [the output](#output--o) option, and is the directory that will be collected in the context of result collection. The content will be (recursively) copied at the end of the task (whether the task succeeded or failed) *if you specified the output option*.
  
There is a fifth mount under the hood that you do not need to bother with: /tmp. It is mounted in a large space of the worker and will be cleaned for you - if the task succeeded. But then in the context of cloud worker, unless you pause everything, the deletion of the worker will delete all these files, even if the task was failed. So if keeping the files is important, use /output. 

Dockers are run with --rm option so as to minimize cleaning tasks in permanent workers, which means anything out of these directories will be deleted once the task is over, whether it succeeded or not.

If you have private images, then you can use a private registry, but you have to configure it, which is explained in [private registry management](specific.md#docker-private-image-registry-management).

### No docker?

Docker is not mandatory, but then several difficulties arise:

- how to install some packages or commands?

There is nothing (yet) in scitq to help you directly with that. The first thought is to tweak Ansible code so that as to complete worker install with other packages. Even a minimal knowledge of Ansible will make this option possible. Another simpler possibility is to use NFS at least in that context: put your binaries somewhere in /data/ and you are good to go. Then you could also bring some binaries as a resource, see below. Remember /data works also without docker, it will be mounted for you in your workers.

- how to have input(s), resource(s), and output(s) without docker?

These options also work out of docker context. However, they are not available in their usual directories (/input, /resource and /output), they are available in directories contained in environment variables that will be available in the execution context of your command, INPUT, RESOURCE and OUTPUT. So if your command is described in a shell script, you could do:
```bash
#!/bin/bash
cd $INPUT
mysubcommand1 -db $RESOURCE/my.db *.fastq > $OUTPUT/myoutput.txt
```

!!! note
    `$OUTPUT`, `$INPUT`, `$RESOURCE` and `$TEMP` special variables contain strings **without a final slash** which makes script writing more natural (like above) as it is far easier to add a needed slash than to remove an unneeded one in the shell.

!!! note
    `$CPU` is the only special variable **available with or without docker**: it contains the number of CPU divided by the concurrency.

!!! note
    These variables are shell environment variables, which means they are only available when using the shell (or using specific libs like `os.environ` when using python), so this command will not output anything `scitq-launch 'echo $CPU'` while this command should  `scitq-launch sh -c 'echo $CPU'`.

### input (-i)
As explained above this option let you specify some files that will be downloaded before the task is launched and available in `/input` folder or in the folder stored in `INPUT` environmental variable if you do not use docker.

You can specify several time this option so that as to have several input files. The file should be specified as a URI, here are the available possibilities:

- `ftp://...` : an anonymous FTP link to a file (no recursive folder),
- `s3://...` : an S3 link which requires that [S3](specific.md#aws-or-others-s3) was properly set up,
- `azure://...` : an Azure link which requires that [Azure storage](specific.md#azure_storage) was properly set up, (Microsoft standard of using https://... URI for Azure was not followed so as to be similar to S3, which keeps the endpoint as a parameter, and because plain https:// file transport maybe added in the future). The standard way of specifying an Azure path is `https://<storageaccount>.blob.core.windows.net/<container>`, which translates in the scitq form as `azure://<container>`.
- `fasp://...` : an IBM Aspera link, used notably in bioinformatics,
- `file:///....` : a local file in the worker, thus unlikely to be suitable except in specific contexts where files are brought to the worker by means not provided by scitq.

For S3 and Azure, if the URI ends with `/` then it is understood as a recursive fetch.

Specifically for bioinformatics (and it is in fact the only thing really specific for that field in scitq), there is a dedicated custom URI called run+fastq:

- `run+fastq://myrunaccession` where myrunaccession should be replaced with a real SRR... or ERR... run accession and will use any available means to try to grab the FASTQ files associated with this run. It will try EBI ENA first as it is much faster than NCBI SRA, first with EBI ENA FTP link, then NCBI SRA sratools, then EBI ENA Aspera link (Aspera does not work well with several providers unfortunately, notably OVH), and it will loop over these three possibilities a certain number of times (10) until one succeeds.

If you wish to see scitq in action just for this specific input part, that is easy in python:
```python
from scitq.fetch import get
get('run+fastq://ERR3857002', './')
```
(note that sratools or Aspera requires docker to work - which can be done with `apt install docker.io` in Ubuntu)

So for instance, you can say:
```bash
scitq-launch -i run+fastq://SRR5666311 -d ubuntu:latest sh -c 'zcat /input/*.f*q.gz|wc -l' 
```

On workers, input dirs are in `/scratch/<someuniquename>/input`.
NB the `/scratch` thing is unrelated to the eponymous language, it is just a reminder that in the end all in those directories will be scratched once the worker is deleted.

#### New in v1.2.2

scitq.fetch URI now accepts some transport options, which are specified right after the protocol, notably for the custom URL `run+fastq` (used in bioinformatics only). Normally this specific URI type chooses the best transport automatically. However you can now force this choice (notably in some cases we discovered that some sources are corrupted in EBI and fine in NCBI or the other way around):
- `run+fastq@ftp://...` : this forces EBI FTP transport,
- `run+fastq@aspera://...` : this forces EBI Aspera transport,
- `run+fastq@sra://...` : this forces NCBI transport (by default `ftp@aria2`, see below, else sratools)

scitq.fetch `https` and `ftp` transport support `@aria2` option like this, replace `https://...` by `https@aria2://...`  or `ftp://...` by `ftp@aria2://...`. [aria2](https://aria2.github.io/) is a lightweight multi-protocol & multi-source command-line download utility that notably parallelize download tasks by splitting the task in several processes (NB this can cause some ethical dilemma when using public resources as it is very demanding for the resource distribution server, so this option should only be used when the alternative methods have strong issues - which is the case for NCBI sratools which are very slow).

### resource (-r)

Resources are very much like above inputs (and like them you may specify several times -r), except for two things:

- they are shared between tasks. If you specify the same resource for several tasks it will be downloaded once per worker (not the case with input, they are downloaded separately for each task),
- they can be processed, unlike inputs which are downloaded as they are, either adding `|gunzip` or adding `|untar` to the URI, in which case the downloaded file will be un-zipped (the `.gz` file will be replaced by its gunzipped version of itself without `.gz` extension) or untarred (unlike `tar x` and like `gunzip` the tar archive will be deleted after extraction, to save space). `|untar` process any file of `.tar`, `.tar.gz` or `.tgz` extension.
- (new in v1.2.2) you can add `|unzip` to for `.zip` files or `|mv <somefolder>` to move the resource content in subfolder. Note that action cannot be combined (you cannot say `|untar|mv ...`).

The optional processing does not change the rule that a resource is always downloaded once per worker. The initial URI with its optional processing is the only thing that count (hence if the file at the other end of the URI did change, this will not be updated).

For the time being scitq has a very simple model for resources. Everything is really downloaded and processed (in no guaranteed order) in a single resource directory on the worker, namely `/scratch/resource/<someuniquename>`. It is convenient if you need to separate resources in several files (several tar archives for instance) which make downloading more efficient, but beware of collision, if two different archives contain the same subdirectories or files then depending on the execution order which is random, either of them will be present...

New in v1.2.2; If the worker service, scitq-worker, is restarted, the downloaded resources will be remembered and not downloaded again.

An example of resource usage:

```bash
scitq-launch -r 's3://resource/mybigdb.tgz|untar' -d 'mydocker' mycommand --db /resource/mybigdb/mybig.db  
```

### output (-o)

Output is a remote folder where the content of `/output` the folder will be recursively copied (or the content of the folder specified in `OUTPUT` environment variable out of docker context). So contrarily to inputs and resources it takes a directory (or path), it is recursive, and it upload content instead of downloading obviously.

For the time being, only two options are supported: `s3://...` (this requires [S3](specific.md#aws-or-others-s3)) or `file:///data/...` (the latest with [NFS support](specific.md#using-nfs)). 

So for instance, this task will upload an empty helloworld file to `s3://results/test/helloworld`:
```bash
scitq-launch -o 's3://results/test/' -d 'ubuntu:latest' touch /output/helloworld  
```

### other options


`-O --option`
:    (O is capital o) specify more docker options: the string passed here is passed as it is when in docker call after the `--rm` and the different `-v` option (that define input, output, resource, data and tmp). UID and GID are dealt with specific option, look below.

`-u --uid -g --gid`    
:    Specify uid and gid of execution. Be careful out of docker context, this will fail if the corresponding uid/gid are not present on workers. With docker, it does not matter.

`-s`
:    Specify scitq server address. It is simpler to set up `SCITQ_SERVER` environment variable, but this is useful if you have several scitq servers.

`-t`
:    Run a test: do not really launch the task, but rather print what would be the launched task. Useful if you launch your tasks in small bash loops (`for i in $(seq 1 10); do scitq-launch -i s3://input/data/$i.dat -d mydocker mycommand -i /input/$i.dat; done`) to watch for proper variable expansion.

`-n`
:   Give a name to your task. Useful to manage your tasks, we will come to that. Otherwise, tasks have just a task_id (but that's fine so do not worry too much about that).

`--`
:   Like in most shell commands this marks the end of `scitq-launch` options, so that what comes next will be interpreted as the command to launch. It is useful if your command starts with dash (welcome to crapy design) or, which is more likely, in case your docker has a built-in command automatically launched and you just have to provide options (thus starting with dash). By default (without specifying `--` ) 

!!! note
    Be careful when you use quotes and variables with scitq-launch, see [using-variables-and-quote-with-scitq-launch](troubleshoot.md#using-variables-and-quote-with-scitq-launch).

### GPU tasks

**New in v1.2.3**

Before the v1.2.3 version, you could already use GPU instances and tasks, but the GPU drivers had to be manually installed. Since v1.2.3, a minimal detection and support of GPU intances is provided and specific images with drivers are automatically installed.

GPU tasks requires three things:

- A GPU worker (that is a worker with a flavor having tag G, something which you can find using `scitq-manage flavor list --protofilters 'tags#G'`, see [Flavor listing](manage.md#flavor)), with Azure, you will need to apply certain settings for this type of instance, see [Support of GPU with Azure](specific.md#support-of-gpu-with-azure) (NB: OVH does not require any specific settings),
- A GPU enabled container (or no container), such as [Nvidia NGC containers](https://catalog.ngc.nvidia.com/containers),
- A specific docker option to provide access to hardware, the recommande option is `--gpus all`.

Here is an example of deploying a (cheap) GPU worker:
```sh
scitq-manage worker deploy -f 'auto:tags#G' -r auto -P azure -b mygpubatch
```

Here is an example of a GPU task, using an NGC container, and the `--gpus all` docker option:
```sh
scitq-launch -b mygpubatch -d nvcr.io/nvidia/pytorch:23.05-py3 -O '--gpus all' nvidia-smi
```

Alternatively, you can use non-docker tasks, which is simpler but more restricted as the NGC instance image might not contain what you need:
```sh
scitq-launch nvidia-smi
```

The output should look like this:
```
=============
== PyTorch ==
=============

NVIDIA Release 23.05 (build 60708168)
PyTorch Version 2.0.0

Container image Copyright (c) 2023, NVIDIA CORPORATION & AFFILIATES. All rights reserved.

Copyright (c) 2014-2023 Facebook Inc.
Copyright (c) 2011-2014 Idiap Research Institute (Ronan Collobert)
Copyright (c) 2012-2014 Deepmind Technologies    (Koray Kavukcuoglu)
Copyright (c) 2011-2012 NEC Laboratories America (Koray Kavukcuoglu)
Copyright (c) 2011-2013 NYU                      (Clement Farabet)
Copyright (c) 2006-2010 NEC Laboratories America (Ronan Collobert, Leon Bottou, Iain Melvin, Jason Weston)
Copyright (c) 2006      Idiap Research Institute (Samy Bengio)
Copyright (c) 2001-2004 Idiap Research Institute (Ronan Collobert, Samy Bengio, Johnny Mariethoz)
Copyright (c) 2015      Google Inc.
Copyright (c) 2015      Yangqing Jia
Copyright (c) 2013-2016 The Caffe contributors
All rights reserved.

Various files include modifications (c) NVIDIA CORPORATION & AFFILIATES.  All rights reserved.

This container image and its contents are governed by the NVIDIA Deep Learning Container License.
By pulling and using the container, you accept the terms and conditions of this license:
https://developer.nvidia.com/ngc/nvidia-deep-learning-container-license

Fri Aug 16 11:28:18 2024
+---------------------------------------------------------------------------------------+
| NVIDIA-SMI 535.161.07             Driver Version: 535.161.07   CUDA Version: 12.2     |
|-----------------------------------------+----------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id        Disp.A | Volatile Uncorr. ECC |
| Fan  Temp   Perf          Pwr:Usage/Cap |         Memory-Usage | GPU-Util  Compute M. |
|                                         |                      |               MIG M. |
|=========================================+======================+======================|
|   0  Tesla T4                       On  | 00000001:00:00.0 Off |                    0 |
| N/A   33C    P8               9W /  70W |      2MiB / 15360MiB |      0%      Default |
|                                         |                      |                  N/A |
+-----------------------------------------+----------------------+----------------------+

+---------------------------------------------------------------------------------------+
| Processes:                                                                            |
|  GPU   GI   CI        PID   Type   Process name                            GPU Memory |
|        ID   ID                                                             Usage      |
|=======================================================================================|
|  No running processes found                                                           |
+---------------------------------------------------------------------------------------+
```

## Managing your task executions

Now that you have queued your tasks, the hard work is done, you can recruit your workers, distribute the work and watch it done, relaxing... You can do that either using the [GUI](gui.md) or using [scitq-manage utility](manage.md).

## scitq-fetch : a convenient utility

It is strongly advised to use either S3 or Azure storage. While S3 seems to be the de facto standard for object storage, Azure also provides some excellent storage solution with more options than S3 (notably different storage redundancy options, and performance and cost choices). Anyway, either solution provides substantial benefits over simple NFS (the main being that it has a much larger bandwidth) and are preferred. 

This means you are likely to end up moving files back and forth S3 or Azure storage. While you can certainly use the native solutions, which provide the best level of integration with the provider, you have to learn the different way to set them up, and each one has a different syntax. In the case of Azure, you also have to translate the URI as Microsoft Azure standard is not exactly followed. So to provide the end user with a more unified environment, `scitq-fetch` is proposed. It just brings to the command line the `scitq.fetch` library functions, which are what `-i/--input`, `-r/--resource` or `-o/--output` are calling under the hood.

Some examples:
- `scitq-fetch list s3://rnd/data/mylogin` : will list recursively all the content of `s3://rnd/data/mylogin`,
- `scitq-fetch list --not-recursive azure://rnd/data/mylogin` : will list the immediate content of `azure://rnd/data/mylogin`, not recursively, 
- as non recursive listing is common though not the cloud standard, `scitq-fetch nrlist` has been added, it is non-recursive **and** relative (e.g. answers path are relative to the path given, by default list give longer and complete URI) (new in v1.2.3)
- `scitq-fetch sync myfolder azure://rnd/data/mylogin/myfolder` : will synchronize the content of `myfolder` to `azure://...` (so that `myfolder/rep/file1.data` is sent to `azure://rnd/data/mylogin/myfolder/rep/file1.data`),
- `scitq-fetch sync --include '*.data' s3://rnd/data/mylogin/myfolder ./myfolder` : same as above, the other way around, get back some remote folder to some local folder, but only for `.data` files.
- `scitq-fetch delete s3://rnd/data/mylogin/myfolder` : recursively delete the folder `s3://rnd/data/mylogin/myfolder`.

See `scitq-fetch -h` for complete help.

This utility can also be used out of scitq context.

### scitq.fetch

As explained above `scitq.fetch` is the library behind `scitq-fetch` utility (and in fact `python -m scitq.fetch` is really exactly the same as `scitq-fetch`). It comes in handy when coding the logic of the distributed tasks in python.

For instance, instead of :

```python
from subprocess import run

[...]

run(f'aws s3 sync {SAMPLE_SUBDIR} {s3_camisim_config_folder}',
    shell=True, check=True)
```

Use:

```python
import scitq.fetch

[...]

scitq.fetch.sync(SAMPLE_SUBDIR, s3_camisim_config_folder)
```

(this comes from `scitq-camisim.py` in [scitq-examples](https://github.com/gmtsciencedev/scitq-examples)). It is convenient as it provides a simple python integration and it reduces external dependencies (no need to install aws utility).