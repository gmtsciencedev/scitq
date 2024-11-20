{!../README.md!}

## Content

How to read the doc: unsure if this is what you need? Look at the [GUI](gui.md) and read the [usage](usage.md). Sure it is what you need but unsure what you will need? Look at [installation](install.md) and [specific settings](specific.md).

* [installation](install.md): straight to business, install scitq.
* [specific settings](specific.md): extra things you should consider and set up.
* [parameters](parameters.md): detail of all the parameters than can be set.
* [usage](usage.md): now that is properly set up, use scitq and queue your first tasks.
* [GUI](gui.md): monitor (and tune) what's going on in scitq.
* [scitq-manage](manage.md): same as above but for command line lovers.
* [model](model.md): some insights about the underlying model, base API and database.
* [workflow](workflow.md): as specified above, the workflow API offers a higher level API recommanded for more sophisticated workload.
* [motivation](motivation.md): why scitq, and how it came to exist.

## Project layout

    src                   # The python src code (and scitq python package)
    src/scitq/ansible     # The ansible recipes that enable to recruit, install and destroy workers 
    docs                  # The MkDocs documentation source
    templates             # Some templates to help install primarily the server service 
    docker                # The source of scitq-worker and scitq-server dockers (only for testing purpose, do not use in production)

