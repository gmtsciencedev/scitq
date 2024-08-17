This folder is dedicated to static resources describing providers:
- available regions,
- available flavors (or instance size/type),
- prices (if it makes sense),
- eviction rates (e.g. for Azure Spot)

Resources should be updatable through the update.py program.

For each provider `resource.json` must contain:
- regions: a list of available regions
- flavors: a mapping of flavor name: flavor object with flavor object containing:
    - cpu: # vcore
    - ram: memory in Gb
    - disk: disk in Gb
    - bandwidth: bandwidth in Gbs
    - regions: sublist of region where this flavor is available
    - evictions (optional): a mapping of region: mean eviction rate (in %)
    - prices (optional): a price in €/h or a mapping of region: price in €/h
    - tags: a list of keyword within: nvme, gpu, metal


