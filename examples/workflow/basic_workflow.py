from scitq.workflow import Workflow

#wf = Workflow(name='wf1', shell=True, workers_per_task=2, total_workers=1, retry=2, container='alpine', flavor='local')
wf = Workflow(name='wf1', shell=True, workers_per_task=2, retry=2, container='alpine', provider='azure', region='swedencentral', flavor='Standard_D2ads_v5')

for i in range(100):
    s1 = wf.step(
        batch='s1',
        name=f's1:{i}',
        command='sleep 10',
        concurrency=10,
    )
    s2 = wf.step(
        batch='s2',
        name=f's2:{i}',
        command='sleep 20',
        concurrency=5,
        required_tasks=s1,
    )

s3 = wf.step(
    batch='s3',
    name='final',
    command='echo "Done!"',
    required_tasks=s2.gather(),
    concurrency=1
)

wf.run(refresh=1)
print(f'Result is {s3.get_output()}')
wf.clean()


