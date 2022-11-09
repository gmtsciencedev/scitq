{!README.md!}

## Commands

* `pytq-server`     - Launch the main server (the program that distribute the tasks).
    - It also includes the GUI and the API.
* `pytq-worker`     - Launch the worker (the program that does the tasks).
* `pytq-launch`     - Add a new task to the queue.
* `pytq-manage`     - A command line utility to monitor, change tasks, etc.

## Project layout

    src         # The python src code (and pytq python package)
    ansible     # The ansible recipes that enable to recruit, install and destroy workers 
    docs        # The MkDocs documentation source
    templates   # Some templates to help install primarily the server service 

