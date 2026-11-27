from history_of_countries.listening import sample_sections

def test_actual_listening_samples_cover_opening_middle_and_resolved_ending():
    sections=sample_sections(525)
    assert sections[0]==(0,35)
    assert sections[1][0]<262.5<sum(sections[1])
    assert sum(sections[2])==525
    assert sum(length for _,length in sections)<=90
