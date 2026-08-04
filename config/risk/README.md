# Risk configuration

`alpaca-paper-v1.json` records the reviewed limits for the named Alpaca paper account. Decimal values
are strings so parsing stays exact. The loader rejects missing, unknown, duplicate, or malformed
fields.

The configuration validity period does not grant broker authority. Each paper run still needs its
own approved authorization and activation. The first activation may last no more than 24 hours.
