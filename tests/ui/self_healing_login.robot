*** Settings ***
Documentation       Demonstrates the self-healing SeleniumLibrary plugin.
...
...                 The suite uses plain SeleniumLibrary keywords — no
...                 ``Heal.`` prefix — because the plugin overrides
...                 ``Click Element``, ``Input Text``, ``Get Text``, and
...                 ``Wait Until Element Is Visible`` in place.
...
...                 ``Prime Heal Cache`` seeds a fingerprint for a
...                 deliberately-broken locator from the real submit button,
...                 simulating a locator that used to work in a previous run.
...                 The second test asserts the login still succeeds despite
...                 the broken locator, proving the plugin heals via the
...                 cached fingerprint.

Resource            ../../resources/common/imports.resource

Suite Setup         Begin Ui Test
Suite Teardown      End Ui Test

Test Tags           ui    self-healing


*** Variables ***
${HEAL_REPORT}      ${OUTPUT_DIR}/healing/report.html
${BROKEN_SUBMIT}    css=button[data-devin="missing"]


*** Test Cases ***
Broken Locator Heals From Fingerprint
    [Documentation]    Primes the heal cache with a fingerprint copied from
    ...    the real submit button, then clicks via a deliberately-broken
    ...    locator and asserts the login still lands on /secure.
    Open Login Page
    Prime Heal Cache    ${BROKEN_SUBMIT}    ${LOGIN_SUBMIT}
    Input Text    ${LOGIN_USERNAME}    tomsmith
    Input Text    ${LOGIN_PASSWORD}    SuperSecretPassword!
    Click Element    ${BROKEN_SUBMIT}
    Login Flash Should Contain    You logged into a secure area!
    Current Path Should Be    /secure

Healing Report Is Written
    [Documentation]    Produces the HTML summary of healing events for archival.
    ${path}=    Write Healing Report    ${HEAL_REPORT}
    File Should Exist    ${path}
