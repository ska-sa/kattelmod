#!groovy

@Library('katsdpjenkins') _
katsdp.setDependencies(['ska-sa/katsdpdockerbase/master'])
katsdp.standardBuild(python2: false, python3: true)
katsdp.mail('ludwig@ska.ac.za')
