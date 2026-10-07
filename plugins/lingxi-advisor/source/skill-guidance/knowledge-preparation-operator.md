## CodeHelix deployment policy

Check `lingxi.advisor.knowledge_preparation_capabilities` before preparing knowledge or starting
a batch. Supported generation modes are not proof that model credentials or a
batch input have been configured. Operator generation currently requires an
independently configured model; Runtime sampling availability does not satisfy it.

Use public task context and the server-owned batch input. Request persistent
pre-retrieved updates only when the server allows them and the user intends the
update. Respect disabled clone, fetch and refresh permissions. Report failures
and their returned retryability without claiming missing output was published.
