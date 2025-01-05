### Intent
* Create a Scalable ML inference server using pulimi

## Steps Highlevel
* Create a docker image with a inference server which can use hugging face to get the model and then serve it.


### Delete only specific resources

- Show all URNs

```pulumi stack --show-urns```


- Destroy only master and workers
```
pulumi destroy \
--target "urn:pulumi:mlOps::ml-inference::aws:ec2/instance:Instance::ml-master" \
--target "urn:pulumi:mlOps::ml-inference::aws:ec2/instance:Instance::ml-worker-0" \
--target "urn:pulumi:mlOps::ml-inference::aws:ec2/instance:Instance::ml-worker-1" \
--target "urn:pulumi:mlOps::ml-inference::aws:ec2/instance:Instance::ml-worker-2" \
-y && pulumi up -y
```

