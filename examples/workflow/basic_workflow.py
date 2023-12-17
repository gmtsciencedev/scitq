from scitq.workflow import Workflow

wf = Workflow(name='wf1', shell=True, maximum_workers=2, retry=2, container='alpine')
#wf = Workflow(name='wf1', shell=True, maximum_workers=2, retry=2, container='alpine', provider='azure', region='swedencentral')

for i in range(100):
    s1 = wf.step(
        batch='s1',
        name=f's1:{i}',
        command='sleep 10',
        flavor='local',
        #flavor='Standard_D2ads_v5',
        concurrency=10,
    )
    s2 = wf.step(
        batch='s2',
        name=f's2:{i}',
        command='sleep 20',
        flavor='local',
        #flavor='Standard_D2ads_v5',
        concurrency=5,
        required_tasks=s1,
    )

s3 = wf.step(
    batch='s3',
    name='final',
    command='echo "Done!"',
    flavor='local',
    #flavor='Standard_D2ads_v5',
    required_tasks=s2.gather(),
    concurrency=1
)

wf.run(refresh=1)
print(f'Result is {s3.get_output()}')
wf.clean()


