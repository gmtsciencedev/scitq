# scitq : a distributed scientific task queue

Item|Project site
--|--
Source|[https://github.com/gmtsciencedev/scitq](https://github.com/gmtsciencedev/scitq)
Documentation|[https://scitq.readthedocs.io/](https://scitq.readthedocs.io/)
Download|[https://pypi.org/project/scitq/](https://pypi.org/project/scitq/)
Docker images|[worker](https://hub.docker.com/r/gmtscience/scitq-worker) and [server](https://hub.docker.com/r/gmtscience/scitq-server)
Examples|[https://github.com/gmtsciencedev/scitq-examples](https://github.com/gmtsciencedev/scitq-examples)
Keywords|task, queue, job, python, distributed, science


**scitq** is a distributed task queue on steroids. Coded in python, it focuses on optimization 
and ease of use. Optimization can be done by tuning the tasks flow in a running process, 
looking in real time at the workers stats and the different tasks' output. 

A task is anything that can be expressed as a Unix command, and can be a complex script that 
can be edited while the process is running. scitq has a focus on relatively heavy tasks (e.g. 
"scientific tasks"): it manages thousands one hour-long tasks better than a million one second-long
 tasks (a scenario for which we strongly recommend Celery).

It has a few added capabilities apart from strict task distribution:

- First it has the capacity to manage cloud instance life cycle (as for now 
OpenStack (OVH), Microsoft Azure, and others to follow) - Note that you can still use 
scitq without using that functionality, and you may use it in a mixed environment
(with one or several static servers plus extra temporary servers recruited on the
cloud). 
- next, scitq has the capacity to download and upload specific data - notably 
using s3 buckets, or Azure containers as data exchange medium, but simple ftp is also possible,
and even some more exotic stuff like IBM Aspera, last a very specific protocol for 
bioinformatics dedicated to downloading public FASTQs (DNA sequence) from EBI or
 NCBI, and all rclone compatible storages are available.
- it integrates nicely with docker, providing support for private registries, and wrapping docker executions in a simple yet efficient way,
It provides a simple data slot paradigm for docker: data input slots or data output slots 
are always in the same place (/input or /output) (in non-dockerized environment,
shell environment variable INPUT and OUTPUT hold the dedicated directories for
these, so docker remains non-mandatory in scitq).

## What it does, and what it does not

**scitq** is a practical tool; it is meant as a cloud solution to dispatch a series of tasks and monitor them. It tries to do just this job in a convenient way, not getting in the middle. In a lot of competitive tools, once a series of tasks is launched, there is very little you can do: this is where scitq is at its best: 

- you can pause all the tasks to fix something amiss,
- you can change the command executed for the future tasks without relaunching the whole series,
- you can resume and relaunch very easily any failed task with or without changing the command (with UI or command line tools, no code needed),
- you can watch (almost - 5s) live the output of any individual task(s) using UI or command line,
- you can adjust execution parameters (like concurrency or prefetch),
- you can add or remove working nodes during execution,
- scitq code can be patched while a task series is running (client and/or server code),
- it is resilient to network troubles,
- loss of a node or temporary server loss (24 hours) should have very limited impact,
- you can mix different cloud resources in the same series (using S3, OVH, and Azure together if that is what you want),
- you can express a complex workflow of different steps and tasks dependencies, which may be simpler to create and maintain than workflows within a task that was the only possibility with previous versions.

It provides convenient utilities such as scitq-fetch which can replace specialized tools like AWS or Azure tool and address the different storages the same way.

scitq provides two design possibilities:
- a simple task and worker management library called `scitq.lib` which is akin to `Celery` and very straight forward (queue some tasks, recruit a worker, you're done), but provides limited management goodies (dynamic worker allocation is complex to set up, debug capacities are limited),
- a Workflow creation library, `scitq.workflow` which provides something more akin to `Nextflow`, i.e. chaining more or less complexe interdependant tasks. There are however several notable differences with `Nextflow`:
  - this is not a different language, this is plain python, where you import a plain python module, not Groovy in a yaml file,
  - Nextflow is more abstract and borrows from the declarative style (which is neither better nor worse, see below),
  - faithful to its practical philosophy, scitq Workflow style provides a writing style easy to read in this task chaining situation. Workflows contain Tasks, the same objects that are used in `scitq.lib`, not theoritical steps : if you have several independant task chains at one point or another in the Workflow you'll have to make a python loop to declare them. While it may lack some abstract design purity, it is considerably easier to use in difficult case of splitting and merging, or to adapt to different kind of initial input.
  - this is python, you can use introspection to query your tasks live, and chat with them in a shell, asking for help or news.

Thus, you are free to use either style, and said simply `scitq.lib` is more adapted to simple tasks (including very big tasks), while `scitq.workflow` is better when different kind of tasks are involved with some dependancies.


## Introduction

**scitq** is a Task Queue system based on the following model:

- a server hosts a series of (shell) tasks to be executed,
- some workers connect to the server, fetch some tasks according to their capacity
(which is very simply managed by the maximum number of parallel processes they can
handle, a.k.a. "concurrency"),
- The stdout/stderr of the command is regularly (all 5s or so) sent to the
server. A task may be executed several times (for instance, if it fails). While
this is not automatic, it is easy to trigger and each execution of the task is
remembered.

### Quick start

Install:
```bash
pip install scitq
```

Now in one shell, run the server:
```bash
FLASK_APP=scitq.server flask run
```

In another shell, launch the worker:
```bash
scitq-worker 127.0.0.1 1
```

In a third shell, queue some tasks:
```bash
scitq-launch echo 'Hello world!'
```
You're done!

Optionally look at http://127.0.0.1:5000/ui/ to see what happened.

Look into the [documentation](https://scitq.readthedocs.io/) to learn about the different options.


### A more elaborate example

Let's dive in some code that does really something. Let's say you want to run fastp to assess the quality of all public FASTQs of a given publicly available project.


#### a minimal server and some worker(s)

we want to minimize the setup in that example, so we will run the server in debug mode. 

We'll deploy the worker manually, but maybe on another server, not the same as the scitq-server. But you can use the same server if you prefer. You can also deploy several workers. We will refer to those servers that run scitq-worker as "workers".

On the scitq-server server, install scitq:
```bash
pip install scitq
```

You will need also rclone, install it as your distribution recommand, for instance on Ubuntu:
```sh
apt install -y rclone
```

We will use an S3 storage. Configure it the usual way with `rclone` (see [s3 config](https://rclone.org/s3/) on rclone site), call the resource `s3` within `rclone`. This is because scitq integrate with rclone, so when you specify `xxx://....` in scitq, scitq will try to find a resource called `xxx` in rclone, thus naming the resource `s3` will make our URIs look like standard s3 URIs: `s3://....`. Now copy `~/.config/rclone/rclone.conf` to `/etc/rclone.conf`. We will also need to create a bucket, which we will call `mybucket` (or adapt the code replacing mybucket by your real bucket name).

On remote servers, when I run long-term tasks, I usually use GNU screen or tmux. But then again, you can open several SSH connections if you prefer.

On the scitq-server server, we will need two open shells, one with the server running, with this command:
```bash
FLASK_APP=scitq.server flask run
```

And the other to be able to run some code.

On the worker(s), install scitq as well (same as above, with pip), but we will also need docker and rclone (which are installed using `apt install -y docker.io rclone` in Ubuntu):

Copy rclone configuration either manually copying `rclone.conf` to `/etc` or using
```bash
scitq-manage config rclone --install
```

and then run in a shell:
```bash
scitq-worker <IP of scitq server> 1
```

A minimal setup, but enough for what we need to do. In a production setup, you'd want scitq to deploy the workers automatically for you, but that requires ansible install and setup, we'll come to that later.

#### running the tasks

First we want to get a list of all the runs and samples, and we will use ENA API to do so, and fortunately for us there is a convenient utility for that in scitq, `scitq.bio.genetics.sra_get_samples()`:

I recommand installing `typer` which is an extremely easy way to create a command line interface, do this with `pip install typer`.


```python
import typer
from scitq.bio.genetics import sra_get_samples

def prepare_bioproject(project:str):
  """Fetch and clean a bioproject FASTQs with fastp"""
  samples = sra_get_samples(project)

if __name__=='__main__':
  typer.run(prepare_bioproject)
```

Next for our task, we need to download the FASTQs, but scitq will take care of that for us, which we will see just after. Next we must pass them to fastp. We need to find a docker image with fastp included. We could, of course, build our own and use conda to install fastp, but here we are lucky and some nice people from StaPH-B did that for us, the docker image is public and called: staphb/fastp.

We will run this rather classical fastp command (suited for single reads):
```bash
zcat *.f*q.gz |fastp --stdin --out1 $sample.fastq.gz --json $sample-fastp.json --cut_front --cut_tail --n_base_limit 0 --length_required 60 \
  --adapter_sequence AGATCGGAAGAGCACACGTCTGAACTCCAGTCA --adapter_sequence_r2 AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGT
```

scitq will take care of collecting the output for us, but we'd like to have fastp json reports collected as well, and also get back the cleaned FASTQs. This is where our S3 storage will be useful.

So our next function will create the corresponding scitq task using the Server.task_create method, our code will be run on the scitq server, so we will use 127.0.0.1 as the server IP address - but you can also use the public IP or a public name that point to it:
```python
import typer
from scitq.bio.genetics import sra_get_samples
from scitq.lib import Server

def prepare_bioproject(project:str):
  """Fetch and clean a bioproject FASTQs with fastp"""
  samples = sra_get_samples(project)
  s=Server('127.0.0.1')
  tasks = []
  for sample, runs in samples.items():
    task.append(
      s.task_create(
        command = f"zcat /input/*.f*q.gz |fastp --stdin \
          --out1 /output/{sample}.fastq.gz \
          --json /output/{sample}-fastp.json \
          --cut_front --cut_tail --n_base_limit 0 --length_required 60 \
          --adapter_sequence AGATCGGAAGAGCACACGTCTGAACTCCAGTCA \
          --adapter_sequence_r2 AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGT",
        shell=True,
        input = [run.uri for run in runs],
        output = f"s3://mybucket/myresults/{project}/{sample}/",
        container = "staphb/fastp"
      )
    )

  s.join(tasks, retry=2)

if __name__=='__main__':
  typer.run(prepare_bioproject)

```

Ok, here our s.task_create command is obviously doing lots of things, let's look in detail at each argument:

- `command` : you recognize the shell command that we discussed above. We have taken our input files from the `/input/` folder, and we output all we want back in the `/output` folder. Otherwise it is the same command.
- `shell` : by default task are not run within a shell, but here we use a pipe (which is useful because it works even with several files),
- `input` this is where we ask scitq to fetch the public data for us and make it available in the `/input` folder of our docker. We simply gather all the different runs for this sample, and provide the list of run URIs prepared by our ready made function. For inforimation, under the hood it uses a specialized URI that looks like `run+fastq://<run accession>` and that probably only scitq understand. scitq will use whatever works, starting from EBI ftp, then switching to NCBI sratools if it does not work, and trying 10 times (EBI Aspera will also be tempted). As you have noticed we installed nothing for sratools or aspera, but scitq will use the official dockers of those solutions to fetch the data, if it thinks it is needed. (note that `scitq-fetch` is a standalone utility that understands these URIs and can be used outside of scitq, it is included in scitq python package)
- `output` this is where all that is in our docker `/output/` at the end of the task will be copied to. Here you may recognized a completely standard s3 URI (which is due to the fact that our rclone resource is called s3), designating a folder in our s3 bucket, we have an different subfolder for each sample, which is not mandatory in our case as output files have different names for each sample, but is generally advised.
- `container` this is simply the docker image that will be used to run the command.

In the end, the last line, we use a small command (`s.join(tasks)`) to wait for all the tasks to complete, which name is reminiscent of a function much alike in python threading package. It will block python code, waiting that all the task to be completed, making the queuing script end only when all tasks are done. It takes an optional parameter, `retry`, which tells scitq to automatically retry failed tasks two times before giving up. It makes a small reporting log during execution also.

And that's it!

Now you can run it with a bioproject name on your scitq server (let us say it is uploaded to scitq-fastp.py on our scitq server):

```bash
python scitq-fastp.py PRJEB46098
```
(this project is 69 heavy FASTQ so it takes a little while to compute on low end machines).

Now connect to your scitq server on `http://<public-ip-of-server>:5000/ui/` and watch the tasks being distributed. You may also want to increase the prefetch option in workers to tell scitq to prepare the input of several tasks in advance. You may want to increase the concurrency option if your worker(s) have some spare power (several CPU). You may notice that running tasks seem to exceed the concurrency of the worker at some times. It is because the task uploading their results are reported as running, but as the worker does not really work when it upload results, it still frees a running slot. So in fact, tasks are not really running in excess, do not worry.

Note that killing the python script won't stop the tasks. The script is just a queuing script, the engine that runs the tasks is scitq. The simplest way to stop it is to use the `scitq-manage` utility, like you would in production (here we run it on the server, hence the 127.0.0.1):

This first command will prevent any new task to be run.
```bash
scitq-manage -s 127.0.0.1 batch stop -n Default
```
(the `-n Default` option is required because we did not specify a batch in our task_create command, so by default, tasks are in the `Default` batch. batches are just a convenient way of grouping tasks)

This second command will also terminate all running tasks as soon as possible:
```bash
scitq-manage -s 127.0.0.1 batch stop -n Default --term
```

These commands can be reversed by:
```bash
scitq-manage -s 127.0.0.1 batch go -n Default
```

If you want to completely remove any trace of this computation on scitq, just delete the batch:
```bash
scitq-manage -s 127.0.0.1 batch delete -n Default
```

Of course for the purpose of demonstration do not delete the batch and let a few tasks normally end at least.


#### getting back the results

So now your results are all in `s3://mybucket/myresults/PRJEB46098`. You should get them back on the server and see them.

We will use `scitq-fetch` utility:
```bash
scitq-fetch sync s3://mybucket/myresults/PRJEB46098 ./PRJEB46098
```

NB you can use rclone also directly, but scitq provide a more consistent way of naming URI in the context of task management (which is not the direct purpose of rclone)

#### getting back outputs

If you want to get back some task output, which you cannot do if you deleted the batch as shown previously, you can first list the tasks:

```bash
scitq-manage -s 127.0.0.1 task list
```

Then get the output of any task:
```bash
scitq-manage -s 127.0.0.1 task output -i <id of task>
```

You can also group both commands to get a listing of all outputs (the first line enables us to give up the `-s` argument we've used up to now with `scitq-manage`):
```bash
export SCITQ_SERVER=127.0.0.1
scitq-manage task list -S succeeded -H|cut -d' ' -f1|xargs -n 1 scitq-manage task output --output -i
```

In python you would do like that:
```python
from scitq.lib import Server

s=Server('127.0.0.1', style='object')

for task in s.tasks(status='succeeded'):
  print(f'-------------\ncommand:{task.command}\n-------------\noutput:{task.output}\n\n')
```
NB by default the scitq.lib.Server return answers with dictionary objects, translating plainly JSON the usual way in python. However, object notation is nicer in python, so we use the `style='object'` option to pass the dictionaries to argparse.Namespace, which implements the object notation. 

Note that you can also export the task outputs from the task UI (`http://<public-ip-of-server>:5000/ui/task/`) as a json file.

Do not let the debug server continue to run as it does not offer any security and some people could remotely launch commands on your workers... In a production server, accesses are restricted to trusted IPs. This is covered in the install.

For even more complete examples, see [https://github.com/gmtsciencedev/scitq-examples](https://github.com/gmtsciencedev/scitq-examples).