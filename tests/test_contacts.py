import pytest
from core.backups import Backups
from core.chatspaces import Spaces
from core.contacts import Contacts,ContactBody
from core.storage import Store


def test_contacts_scope_revision_search_and_backup(tmp_path):
    store=Store(tmp_path)
    book=Contacts(store)
    item=book.save(ContactBody(name="Алёна",email="friend@example.test",telegram="@friend"))
    assert book.list("АЛЁНА")==[item]
    changed=book.save(ContactBody(name="Алёна",phone="+79990000000"),item["id"],item["updated"])
    with pytest.raises(ValueError): book.remove(item["id"],item["updated"])
    space=Spaces(store)
    project=space.create_project("Проект")
    chat=space.create_chat(project["id"])
    other=Contacts(store.for_chat(chat["id"]))
    assert not other.list()
    with pytest.raises(ValueError): other.save(ContactBody(name="Нельзя"),item["id"],changed["updated"])
    target=Store(tmp_path/"target")
    backup=Backups(target)
    backup.restore(backup.preview(Backups(store).export())["ticket"])
    assert Contacts(target).list()==[changed]
    book.remove(item["id"],changed["updated"])
    assert not book.list()


@pytest.mark.parametrize("data",[{"name":" "},{"name":"a\nb"},{"name":"X","email":"x\nBcc:y@example.test"},{"name":"X","telegram":"\0bad"}])
def test_invalid_contact_fields(data):
    with pytest.raises(ValueError): ContactBody(**data)
