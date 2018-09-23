## JobTree

This is an example CompositeController that's similar to Job,
except that Pods are started only when a given set of other Pods have been
successfully executed.

### Prerequisites

* Install [Metacontroller](https://github.com/GoogleCloudPlatform/metacontroller)

### Deploy the controller

```sh
kubectl create namespace jobtree
kubectl -n metacontroller create configmap jobtree-controller --from-file=sync.py
kubectl apply -f jobtree-controller.yaml
```

### Create a JobTree

```sh
kubectl -n jobtree apply -f my-jobtree.yaml
```

Monitor the jobs being created, run and completed:

```sh
watch -d kubectl -n jobtree get all
```

Monitor log output from the controller:

```console
$ kubectl -n metacontroller get pods | grep jobtree-controller
jobtree-controller-7b798bf8bb-7sb5v   1/1       Running   0          3m
$ kubectl -n metacontroller logs -f jobtree-controller-7b798bf8bb-7sb5v
```

Each Pod created should report its starting, sleeping and completion with
timestamps on their standard output:

```console
$ kubectl logs my-jobtree-a
2018-09-22T18:56:45UTC a starting
2018-09-22T18:56:45UTC a sleeping for 15 s
2018-09-22T18:57:00UTC a done
```

### Failure Policy

To be implemented.


### Remove the controller

```sh
kubectl -n metacontroller delete service jobtree-controller
kubectl -n metacontroller delete deployment jobtree-controller
kubectl -n metacontroller delete compositecontroller jobtree-controller
kubectl -n metacontroller delete crd jobtrees.ctl.enisoc.com
kubectl -n metacontroller delete configmap jobtree-controller
```
