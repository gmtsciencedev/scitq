# Usage

## Task definition 
As said in introduction, scitq is about distributing tasks, but what a task is has not been clearly defined. In the [quick start](../#quick-start), the proposed task is `echo 'Hello world!'`, that is a simple command, with its parameter(s), which make it pretty much what you want, but with some restrictions that are not explicit in that definition. 

This is the only theoritical part of the chapter. If you want to jump into usage, go directly to the next section: [Programming a task](#queuing-a-task)

### self contained
First, the task should be self contained, it should rely on a limited input known before launch time, and depends on a reasonable amount of (read-only shared) resources. There are two specific mechanics to answer to both points in scitq (respectively [input](#input--i) and [resource](#resource--r)). Be aware that scitq is not suited to interdependant tasks: there is a third mechanism to take care of results collection ([output](#output--o)), but this is not accessible by the other tasks that were programmed before the producing task ended.

### atomic
Second, the task should be atomic, that is finish after a certain computation time on its own with a return code, expressed with the Unix paradigm, 0 if it is ok, some other number if it is not. 

It excludes unix services and other never ending tasks, or task whoes ending status is always 0 (usually poorly coded programs) or the other way around. In fact it is not strictly impossible to use such tasks but you will not be able to use the error treatment capability of scitq. It also exclude tasks with user interaction.


### predictible (in terms of requirements: cpu, mem, disk)
That's the last one but not the least. Some programs are extremely nice (like pigz), they let you choose how many thread you will use and consume a reasonable amount of memory, plus they are very constant in their needs (you do not have to monitor them for hours to guess how they will behave). Some programs are very bad in that regard, they tend to be very variable in their needs during their computation time and they offer little or no control over it. They are not impossible to work with but will give you a hard time.

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

This will ask any available worker in the default batch to execute this command. Batch is used by scitq to separate things. Each batch is just a name (a character string, generally short something like `assembly_genome_ecoli`), that is associated with one or several tasks and one or several workers. Each batch is completely independant of another, so a task associated with a certain batch is invisible to workers associated with another. When a task or a worker is created without a batch, it belongs to the default batch. While it is fine if you work alone and you do one list of task at a time, in a team, it is advised never to use the default batch. That's what we'll do with `-b` option:

```bash
scitq-launch -b mybatch mycommand --myoption myarg
```

### docker (-d)

One of the tricky thing with delegating the execution of a command is the notion of context. The context of your shell (maybe with a conda environment) is very specific, and is not the context of execution of the worker (remember the worker run as root). Especially when the worker is not on the same server. Containers and docker in particular offer a very fine solution to that issue, and we will consider you have a *public* docker that suit your needs, so that you would have launch your command like that:

```bash
docker run mypublicdocker mycommand --myoption myarg
```

Then queuing would be simply like this (we did not repeat above option `-b mybatch` to make things very simple, but it should be added):
```bash
scitq-launch -d mypublicdocker mycommand --myoption myarg
```

Then generally with docker, you mount volume(s) with docker -v option so that you can access some external files to the docker and recover some results file. Here scitq will automatically propose several mounts or mapping automatically. There are 4 of them:

- /data : it is used in [NFS](specific.md#using-nfs) context. If you activated NFS support in scitq then /data will be available in /data in the docker context (it is the only mount available also out of docker context),
- /input : we will cover that just after with [input](#input--i) option, if you specify any input option, the files will be made available to your task in that folder,
- /resource : it is very much like /input, but related to [resource](#resource--r) option. The difference with input is that resources are shared between tasks.
- /output : it is linked to [output](#output--o) option, and is the directory that will be collected in the context of result collection. The content will be (recursively) copied at the end of the task (whether the task succeeded or failed) *if you specified the output option*.
  
There is fifth mount under the hood that you do not need to bother with: /tmp. It is mounted in a large space of the worker and will be cleaned for you - if the task succeeded. But then in the context of cloud worker, unless you pause everything, the deletion of the worker will delete all these files, even if the task was failed. So if keeping the files is important, use /output. 

Dockers are run with --rm option so as to minimize cleaning tasks in permanent workers, which means anything out of these directories will be deleted once the task is over, whether it succeeded or not.

If you have private images, then you can use a private registry, but you have to configure it, which is explained in [private registry management](specific.md#docker-private-image-registry-management).

### No docker?

Docker is not mandatory, but then several difficulties arise:

- how to install some packages or commands?

There is nothing (yet) in scitq to help you directly with that. The first thought is to tweak Ansible code so that as to complete worker install with other packages. Even a minimal knowledge of Ansible will make this option possible. Another more simple possibility is to use NFS at least in that context: put your binaries somewhere in /data/ and you are good to go. Then you could also bring some binaries as a resource, see below. Remember /data works also without docker, it will be mounted for you in your workers.

- how to have input(s), resource(s), and output(s) without docker?

These option also work out of docker context. However, they are not available in their usual directories (/input, /resource and /output), they are available in directory contained in environment variables that will be available in the execution context of your command, INPUT, RESOURCE and OUTPUT. So if your command is described in a shell script you could do:
```bash
#!/bin/bash
cd $INPUT
mysubcommand1 -db $RESOURCE/my.db *.fastq > $OUTPUT/myoutput.txt
```

!!! note
    `$OUTPUT`, `$INPUT`, `$RESOURCE` and `$TEMP` special variables contain strings **without a final slash** which makes script writing more natural (like above) as it is far easier to add a needed slash than to remove an unneeded one in shell.

!!! note
    `$CPU` is the only special variable **available with or without docker**: it contains the number of CPU divided by the concurrency.

### input (-i)
As explained above this option let you specify some files that will be downloaded before the task is launched and available in `/input` folder or in the folder stored in `INPUT` environmental variable if you do not use docker.

You can specify several time this option so that as to have several input files. The file should be specified as a URI, here are the available possibilities:

- `ftp://...` : an anonymous FTP link to a file (no recursive folder),
- `s3://...` : an S3 link which requires that [S3](specific.md#aws-or-others-s3) was properly set up,
- `fasp://...` : an IBM Aspera link, used notably in bioinformatics,
- `file:///....` : a local file in the worker, thus unlikely to be suitable except in specific contexts where files are brought to the worker by means not provided by scitq.

Specifically for bioinformatics (and it is in fact the only thing really specific for that field in scitq), there is a dedicated custom URI called run+fastq:

- `run+fastq://myrunaccession` where myrunaccession should be replaced with a real SRR... or ERR... run accession and will use any available mean to try to grab the FASTQ files associated with this run. It will try EBI ENA first as it is much faster than NCBI SRA, first with EBI ENA FTP link, then NCBI SRA sratools, then EBI ENA Aspera link (Aspera does not work well with several providers unfortunately, notably OVH), and it will loop over these three possibilities a certain number of time (10) until one succeed.

If you wish to see scitq in action just for this specific input part, that is easy in python:
```python
from scitq.fetch import get
get('run+fastq://ERR3857002', './')
```
(note that sratools or Aspera requires docker to work - which can be done with `apt install docker.io` in Ubuntu)

So for instance you can say:
```bash
scitq-launch -i run+fastq://SRR5666311 -d ubuntu:latest sh -c 'zcat /input/*.f*q.gz|wc -l' 
```

On workers, input dirs are in `/scratch/<someuniquename>/input`.
NB the `/scratch` thing is unrelated to the eponymous language, it is just a reminder that in the end all in that directories will be scratched once the worker is deleted.

!!! note
    New since version 1.0b19 and above (1.0rcX versions are above 1.0bX versions), and **only with S3**, an input can end with a trailing slash which means recursively import all the directory as input. This can be convenient notably when you chain tasks (as output is recursive itself).

### resource (-r)

Resources are very much like above inputs (and like theom you may specify several times -r), except for two things:
- they are shared between tasks. If you specify the same resource for several tasks it will be downloaded once per worker (not the case with input, they are downloaded separately for each task),
- they can be processed, unlike input which are downloaded as they are, either adding `|gunzip` or adding `|untar` to the URI, in which case the downloaded file will be un-zipped (the `.gz` file will be replaced by its gunzipped version of itself without `.gz` extension) or untarred (unlike `tar x` and like `gunzip` the tar archive will be deleted after extraction, to save space). `|untar` process any file of `.tar`, `.tar.gz` or `.tgz` extension.

The optional processing does not change the rule that a resource is always downloaded once per worker. The initial URI with its optional processing is the only thing that count (hence if the file at the other end of the URI did change, this will not be updated).

For the time beeing scitq has a very simple model for resources. Everything is really downloaded and processed (in no guarrantied order) in a single resource directory on the worker, namely `/scratch/resource/<someuniquename>`. It is convenient if you need to separate resources in several files (several tar archives for instance) which make downloading more efficient, but beware of collision, if two different archives contain the same subdirectories or files then depending on the execution order which is random, either of them will be present...

If the worker service, scitq-worker, is restarted, then a new resource directory will be picked up and all previously downloaded resource will be forgotten and downloaded anew if they are requested again by some task.

An exemple of resource usage:

```bash
scitq-launch -r 's3://resource/mybigdb.tgz|untar' -d 'mydocker' mycommand --db /resource/mybigdb/mybig.db  
```

### output (-o)

Output is a remote folder where the content of `/output` folder will be recursively copied (or the content of the folder specifed in `OUTPUT` environment variable out of docker context). So contrarily to inputs and resources it takes a directory (or path), it is recursive, and it upload content instead of downloading obviously.

For the time being, only two options are supported: `s3://...` (this requires [S3](specific.md#aws-or-others-s3)) or `file:///data/...` (the latest with [NFS support](specific.md#using-nfs)). 

So for instance, this task will upload an empty helloworld file to `s3://results/test/helloworld`:
```bash
scitq-launch -o 's3://results/test/' -d 'ubuntu:latest' touch /output/helloworld  
```

### other options


`-O --option`
:    (O is capital o) specify more docker options: the string passed here is passed as it is when in docker call after the `--rm` and the different `-v` option (that define input, output, resource, data and tmp). UID and GID are dealt with specific option, look below.

`-u --uid -g --gid`    
:    Specify uid and gid of execution. Be carefull out of docker context, this will fail if the corresponding uid/gid are not present on workers. With docker, it does not matter.

`-s`
:    Specify scitq server address. It is more simple to set up `SCITQ_SERVER` environment variable, but this is useful if you have several scitq servers.

`-t`
:    Run a test: do not really launch the task, but rather print what would be the launched task. Usefull if you launch your tasks in small bash loops (`for i in $(seq 1 10); do scitq-launch -i s3://input/data$i.dat -d mydocker mycommand -i /input/$i.dat; done`) to watch for proper variable expansion.

`-n`
:   Give a name to your task. Usefull to manage your tasks, we will come to that. Otherwise, tasks have just a task_id (but that's fine so do not worry too much about that).

`--`
:   Like in most shell command this marks the end of `scitq-launch` options, so that what come next will be interpreted as the command to launch. It is useful if your command starts with dash (welcome to crapy design) or, which is more likely, in case your docker has a builtin command automatically launched and you just have to provide options (thus starting with dash). By default (without specifying `--` ) 

!!! note
    Be careful when you use quotes and variables with scitq-launch, see [using-variables-and-quote-with-scitq-launch](troubleshoot.md#using-variables-and-quote-with-scitq-launch).

## Managing your task executions

Now that you have queued your tasks, the hard work is done, you can recruit your workers, distribute the work and watch it done, relaxing... You can do that either using the [GUI](gui.md) or using [scitq-manage utility](manage.md).