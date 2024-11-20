# Using the scitq-manage utility

scitq-manage is meant as a command line solution to do all the actions that can be done using the GUI. 

## syntax

```bash
scitq-manage [<global options>] <object> <verb> [<verb options>]
```

The command takes two words, a first word that define the type of object you want to address, the second the action that must be performed. 

The different objects are:

- worker
- task
- batch
- execution (new in v1.2)
- recruiter (new in v1.2)
- flavor (new in v1.2.3, it only accept the list action, see below)

Three specific objects will be detailed later as they have very specific actions:

- ansible (used when installing or debuging)
- db (used when installing)
- debug (used when debuging)
- config (used when installing)

The actions are:

- list
- delete
- update (only worker, task)
- deploy (worker only)
- relauch (task only)
- output (task only)
- stop (batch only)
- go (batch only)
 

scitq-manage has an extensive inline documentation, you can launch 

- `scitq-manage -h` to get a global help message
- `scitq-manage <object> -h` to get some help on the action you can perform on a certain type of object (for instance `scitq-manage worker -h`)
- `scitq-manage <object> <verb> -h` to get some help on the options for a certain action (for instance `scitq-manage worker list -h`)

So this documentation will not go in all the details that comes with the inline help and are more accurate. The idea is just to give some examples.

## global options

There are only two of them:
`-s`
: only usefull if you do not have SCITQ_SERVER environment variable set, or if you can reach several servers. This is the server IP address or FQDN (not the URL, do not say :5000, the 5000 port is known)

`-t`
: timeout. By default there is a 150s timeout to get the result to a certain query. This is almost ever much more than required. However for some very specific heavy task involving large data management, increasing the timeout is a good idea (see [troubleshooting](troubleshoot.md#big-outputs)).

## worker

### list 

This will list the different worker in the manner of the [worker screen](gui.md#worker-screen-httpui). The handy `-L` option will display all the attributes (prefetch, and the different counters for the task success or failures).

```bash
scitq-manage worker list   

  worker_id  name          status      concurrency  creation_date               last_contact_date           batch
          1  epeire.local  running               1  2022-11-16 08:25:25.747354  2022-11-16 08:28:14.738917  Default
```

```bash
scitq-manage worker list -L

  worker_id  name          status      concurrency  creation_date               last_contact_date           batch      prefetch  assigned    accepted    running    failed    succeeded
          1  epeire.local  running               1  2022-11-16 08:25:25.747354  2022-11-16 08:27:42.418281  Default           0
```

### deploy

This will recruit a new worker using Ansible (with the same options as in the GUI [worker recruit](gui.md#recruiting)).

For instance this will deploy the same simple worker as in the GUI document:
```bash

scitq-manage worker deploy -f d2-2 -r GRA11 -P ovh -b mybatch
```

With `-f` being the flavor, `-r` the region of deployment for the provider, `-P` the provider, and `-b` the batch for which the worker is recruited. Using `scitq-manage flavor list`, see [flavor](#flavor) below, you will obtain a list of available flavor.

#### Using protofilters (new in v1.2.3)

!!! note
    If updaters are not setup properly protofilters (or `flavor find`) will not find any available flavors as flavor list is empty by default.

Protofilters is a new term coined to denote a system of filters intended to chose automatically the *best* available flavor available among the different providers (or within a provider, as the catalog of flavors may be quite long). This functionality requires a specific setup, see [OVH updater](specific.md#ovh-updater) and/or [Azure updater](specific.md#azure-updater), as it requires scitq to know about the different flavors available. Of course, *best* will largely depend on what are your requirements for the worker(s). This is where the filters come: they enable you to require a certain number of cpu (with an expression like `cpu>=10` for instance), or some memory size, using the `ram` (random access memory) keyword. Apart from this criteria, *best* in protofilters means *cheapest*, exactly as in [flavor list](#flavor) below (under the hood, protofilters and `flavor list` use the same function, `scitq.server.model.find_flavor()`).

This is simply triggered by providing `auto:...` as the name of the flavor, with the three dots being a list of `:` separated filters. So for instance to get the best flavor with at least 10 CPUs (or vcores), the flavor would have to be set to `auto:cpu>=10`. If in addition, you need a minimal amount of memory, let's say 100 Gb, then add the requirement:
`auto:cpu>=10:ram>=100`. If you have a certain amount of data that needs to be uploaded on the worker, let's say 200 Gb, remember to add a disk requirement, like this: `auto:cpu>=10:ram>=100:disk>=200`. This last example is a typical real-life protofilter chain. You can also specify other filters, see below [protofilters details](#protofilters-details).

!!! note
    In shell `>` and `<` are reserved characters (for standard input, output and error flow redirection). As they are commonly used in protofilters, you should very likely protect the protofilters with single quotes. For instance, this syntax will be ok:
    ```sh
    scitq-manage worker deploy -f 'auto:cpu>10' -P azure -r northeurope
    ```
    Where this syntax will fail:
    ```sh
    scitq-manage worker deploy -f auto:cpu>10 -P azure -r northeurope
    ```
    

When using protofilters, e.g. setting the flavor as `auto:...`, there are two possibilities for the `-P` provider parameter and the `-r` region parameter: use them as usual, which will act as constraints for the filters (e.g. choose the best flavor with theses requirement *using this specific provider*/*available in this specific region*). If you wish to leave all possibilities opened, you will need to provide `auto` for either parameters. Although, generally it is not recommanded to use `auto` for the provider, see the note at the bottom of this paragraph.

For instance this will chose the best available flavor with more than 10 CPUs, more than 100 Gb memory, and more than 200 Gb of disks, accross all providers without any region consideration:

```sh
scitq-manage worker deploy -f 'auto:cpu>=10:ram>=100:disk>=200' -P auto -r auto
```

!!! note
    As always there are lots of subtelty when using cloud services. While the above expression will provide you with the cheapest worker, it may not be the best economical setup. For instance, there are increased transfer costs when transfering data from one region to another, so depending on where the data will be stored, you may want to chose the same region or a region nearby to reduce fees (and maybe to increase performances). There is a simple trick in the installation procedure to optimize this (the preferred region), so as a user, you should generally avoid specifying auto as the provider, but choose the provider that matches the data provider. As a simple rule of thumb, inbound data is not subjected to fees while outbound data is subjected to fees, the farthest, the worse. 

##### Protofilters details

For REGEXP lovers, protofilters python REGEXP is the following:

`^(?P<item>cpu|ram|disk|tags|gpumem|eviction|region|cost|provider)(?P<comparator>==|!=|>=|>|<|<=|~|#|!~|!#)(?P<value>[0-9\.]+|[A-Za-z0-9_%-]+)$`

Which roughly translate to:
<item><comparator><value>

Where:

- item would be a term within cpu, ram, disk, tags, gpumem, eviction, region, cost or provider,
- comparator would be something very much like a python comparator: `==`, `!=`, `>=`, `<=`, `>`, `<` or two specific comparators:
  - `~` (coined *like*) which is an extension of `==` for string with a wide character (`%`) exactly like the SQL `LIKE` comparator, and ressembling shell/DOS expression where `*` is used as a wide character, as in `ls *.py` (remember than in SQL and scitq the wide characeter is `%` instead of `*`)
  - `#` (coined *has*) is used for tags. Tags are collection of letters that describes specific characteristics of the flavor, see below tags. The `#` comparator means that the letters after the `#` should be present in the tags.
  - both `~` and `#` are available in their negated version, `!~`(e.g. *not like*) and `!#`(e.g. *has not*)
- value is a plain value, not quoted, thus the difference between a number and a string is that that the string is not expected to start with a number (or a dot).

Item details:

- `cpu`: value should be a number, the number of CPUs/vcores of the flavor,
- `ram`: value should be a number, the size in Gb of the RAM memory of the flavor,
- `disk`: value should be a number, the size in Gb of the disk of the flavor,
- `tags`: value should be a string of one or more letter within `G`, `M` or `N`, and most likely the comparator should be `#` or `!#`, but `~`, `==`, `!~` and `!=` are acceptable and may make sense in specific scenarios, the tags may contain 
  - `G` (for GPU, e.g. the instance has a GPU, see also `gpumem` below), 
  - `M` (for Metal, e.g. the instance is not a virtual server worker but a physical server worker - note that by default this type of instance is excluded, like if an implicit `tags!#M` is added, as it takes a longer time to deploy, but specifying `tags#M` as a protofilter will find them - as in fact the presence of tags in protofilters remove this automatic filter), 
  - `N` (for NVMe (disks)): this type of instance has ultra quick disks with an access time almost similar to RAM memory. This tags is less reliably set than the two others.
- `gpumem`: value should be a number, the total size in Gb of the GPU RAM memory of the flavor,
- `eviction`: value should be a number, the probability (% per hour) that the created worker is claimed back by the provider (for now, only with azure, for which we use spot). When a worker is evicted (e.g. claimed back), there is an automatic procedure of replacement, however, due to the 3 to 5 minutes of deploy delay, high eviction flavor should be avoided. For this reason, by default a filter corresponding to a maximal eviction of 5% is applied (corresponding to protofilter `eviction<=5`). This automatic filter is removed if a filter mentionning eviction is present.
- `region`: value should be a string, the region in which to choose to the flavor (note that availability may vary frome one region to another). This protofilter is clearly redondant with the `-r` parameter, however it is more flexible here as one can use the like comparator, for instance `region~GRA%`. This may enable a flexible choice that can adjust to actual availability of flavors while retaining a choice that is more optimal for specific reasons. 
- `cost`: value should be a number, the cost in $/h (azure) or €/h (ovh) of the flavor,
- `provider`: value should be a string, like for `region` this is redondant with `-P` parameter. It is proposed potentially for future usage, currently there is no benefit at all using this protofilter rather than the easier `-P` parameter.

### delete

This is the same as clicking on the trash icon right of the worker, for instance this will delete the node1 worker:
```bash
scitq-manage worker delete -n node1
```

### udpdate

This will enable to change concurrency, batch, prefetch of a worker. For instance to change the batch as in the GUI:
```bash
scitq-manage worker update -b test -n node1
```

## task

!!! note
    To launch a task, use `scitq-launch`, cf [usage](usage.md#queuing-a-task). The reason is practical: scitq-manage use python package argparse which makes syntax and inline documentation clear and simple. 
### list

Same as with worker list, use -L option to see all the parameters of the task and the complete command (which will be truncated otherwise)
```bash
scitq-manage task list -L      

  task_id  name    status    command     creation_date               modification_date           batch    container    container_options    input    output    resource
        1          running   sleep 1000  2022-11-16 13:30:19.733077  2022-11-16 13:30:24.114657  test
```

### relaunch

Like [relaunching with the GUI](gui.md#task-screen-httpuitask):

```bash
scitq-manage task relaunch -i 1
```
NB here no choice, our task has no name so we cannot use the `-n` option, we must use the task id with `-i`. You must use one of them.


### output

See the output of a task (stderr and stdout by default, but you can specify `-o` to see only stdout or `-e` to see only stderr):

```bash
scitq-manage task output -i 1
```

### update

Change a property of the task, like the command (`-c`) or the docker image (`-d`):

```bash
scitq-manage task update -i 1 -d ubuntu:latest
```

Unlike the GUI and you can change any property of the task - including the status, thus you can also relaunch a task using:
```bash
scitq-manage task update -i 1 -S pending
```


### delete

Just delete the task:

```bash
scitq-manage task delete -i 1
```


## batch

This mimics the [batch screen](gui.md#batch-screen-httpuibatch) of the GUI.
### list

Contrarily to the other list no option for this one.

```bash
scitq-manage batch list

batch    pending    accepted    running    failed      succeeded  workers
test                                                           1  epeire.local
```

### stop/go

This will pause the batch (the simple pause only) and relaunch the batch.

```bash
scitq-manage batch stop -n test
```

### delete

This will just delete a batch (and all the corresponding tasks)

## flavor

This will list available flavor matching some criteria. Thus only `list` is available.

### list

The only action possible with flavor. It accepts several parameters, all optional, like:

- `--min-cpu` : only flavor with at least this CPU number are listed,
- `--min-ram` : only flavor with at least this size of RAM memory (in Gb) are listed,
- `--min-disk` : same as above with disk size (in Gb),
- `--max-eviction` : see eviction definition above in [protofilters details](#protofilters-details), this default to 5% of max eviction.
- `--limit` : the maximum number of answer listed, by default 10,
- `--protofilters` : see [protofilters](#using-protofilters-new-in-v123), this is a string of `:` separated protofilters, like `cpu>=10`. While this example could be obtained with `--min-cpu` parameter, protofilter syntax is much richer, and for instance `cpu<=20` cannot be expressed in another way. Some protofilters may relieve some builtin restriction:
  - `eviction>=0`: this protofilter will remove any constraint on eviction (by default flavor with eviction above 5 are removed),
  - `tags~%`: this protofilter will remove any constraing on tags (by default metal instances, tags including M, are filtered out) 
  - protofilters do not need to start with `auto:...` which is required only when deploying, apart from that they are really the same, using the same function.
