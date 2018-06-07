#mrbv

Merge request by vote

in Gitlab 

### Install

1. add user (bot) to gitlab and  add private key with api access
2. set ENV in project `Setting -> CI/CD`
    ```bash
    MRBV_BOT_UPVOTE=10
    ```
    if you need take a merge without check pipline add
    ```bash
    MRBV_BOT_IGNORE_PIPELINE=true
    ```
3. add access for Bot to you project (or projects by groups)
4. run bot!
    ```bash
    docker run -it \
    --name merge_bot \
    -e MRBV_URL=https://gitlab.my.company \
    -e MRBV_TOKEN=Joic2lSW-f98sv_das2 \
    negash/mrbv

    ```