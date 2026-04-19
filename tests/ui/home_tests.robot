*** Settings ***
Documentation       Sanity checks on the landing page.

Resource            ../../resources/common/imports.resource

Test Setup          Begin Ui Test
Test Teardown       End Ui Test

Test Tags           ui    home    smoke


*** Test Cases ***
Landing Page Shows Welcome Heading
    Open Home Page
    Home Page Heading Should Be    Welcome to the-internet

Landing Page Exposes Navigation Links
    Open Home Page
    ${count}=    Get Home Link Count
    Should Be True    ${count} > 20    Expected many demo links on landing page
