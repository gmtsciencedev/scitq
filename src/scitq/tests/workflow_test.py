from ..workflow import Workflow


wf=Workflow(name='TestWorkflow',
            debug=True,
            shell=True,
            max_step_workers=1,
            flavor='local')

for i in range(3):
    step1 = wf.step('sleep_n_say', command=f'''for i in $(seq 1 {i+1}); do echo $i; ls djuf; sleep 6; done''', concurrency=2)
    step2 = wf.step('sleep_n_say2', command=f'''sleep 2; echo done''', required_tasks=step1, concurrency=2)

wf.run()