# Using the GUI

This option is more simple than the [pytq-manage](pytq-manage.md) option but requires a browser access to PYTQ server (and thus require that you have access to a trusted IP as defined in [security](install.md#security), maybe a VPN or a proxy or an SSH tunnel).

## Reaching the GUI

If the PYTQ server name is `pytq.mycompany.com`, then the GUI URL is `http://pytq.mycompany.com:5000/ui/`.
It should look like that:

![ui-start](img/ui-start.png)

This is the worker screen, it is empty because there are no workers. In the screenshot, all tasks counter are set to zero which means no tasks are queued or were executed.

## worker screen (http://.../ui/)

So if the worker screen is empty, it is time we recruit one. Let us do that: at the bottom of the start screen there is line like this, let us fill it and submit:

### Recruiting
!!! note
    This will not work if you have not properly set up your [provider](specific.md#providers-configuration).

![ui-recruit](img/ui-recruit.png)

`concurrency`
:   leave that to 1 for now. This is the number of task the worker should execute concurrently (together).

`prefetch`
:   leave that to 0, this is an optimisation setup, we do not need that for now.

`flavor`
:   this is OpenStack wording (and thus for OVH or other OpenStack providers as well) for the instance model. `s1-2` is the smallest available instance for OVH (1 vcore, 2 GB mem and 5GB hard drive). Obviously not fit for production, that is enough for a test, so type in s1-2. This will cost you 6€ if you leave it like that for one month, and just the prorata temporis if you shut it down after a while (which we will do very shortly anyway).

`region`
:   when you set your provider up, you established a list of available regions (and you deployed your SSH key on them), pick one of them. GRA11 is a fine choice here if it is available for you, but really, any will do.

`batch`
:   if you read the [usage batch chapter](usage.md#batch--b), you should be familiar with that. It is simply a character string that should be shared between some tasks and some workers. The workers of a certain batch will only take tasks from this particular batch. If you have already queued some tasks (not too big hopefully, remember we are with a very small instance), you can choose the same batch. Otherwise, take `mybatch`, that will do. Anyway it is extremely easy to move a worker from one batch to another.

`number`
:   this is the number of workers we will recruit with those parameters. Let us stay to 1 for now.

now click add.

You should see a line `node1` coming up quickly, but with a grey dot, sign that the worker is not ready yet and then after ~5 minutes (OVH smaller instances are pretty slow to come up), the dot should turn blue and you should see that:

![ui-recruit2](img/ui-recruit2.png)

Note the small red message at the bottom of the screen "done for node1". What happen under the hood is that Ansible playbook `deploy_one_vm.yaml` was played and this is the end message.

### Managing workers

Here are the different options to manage interactively workers. 

!!! note
    Workers are also manage automatically by PYTQ *if you recruited them like we just did*: once they have started working (they have started a first task), if their batch becomes empty and they stay idle for 5 minutes, they will launch the idle callback and PYTQ will delete them - delete them from the worker screen and PYTQ database and also delete them in the provider space. This does not happen with permanent workers (i.e. manually deployed workers).

#### Changing the batch
![edit batch](img/ui-edit-batch.png)
You can edit the batch. This will instruct the worker to accept tasks from a new batch (if some tasks remain (accepted or running) from previous batch, they will finish normally).

#### Concurrency
Just right of batch, you will find the concurrency +/- buttons. Concurrency is the number of tasks allowed to run simultaneously on the worker. Increasing the concurrency will have an instant effect: it is always easy to accept more tasks. But decreasing the concurrency will not be instant: this will just prevent some new tasks to replace the finishing tasks so as to adjust the number of running tasks to the new concurrency. If you want to kill the running tasks, you should go to task management.