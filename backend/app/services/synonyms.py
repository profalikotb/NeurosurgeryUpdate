"""Neurosurgical abbreviation / synonym groups used for query expansion (lexical search).

Each group is treated as equivalent. Keep entries unambiguous inside neurosurgery; extend freely.
"""
from __future__ import annotations

GROUPS: list[list[str]] = [
    ["vestibular schwannoma", "acoustic neuroma", "acoustic neurinoma", "VS"],
    ["cerebellopontine angle", "CPA"],
    ["subarachnoid hemorrhage", "subarachnoid haemorrhage", "SAH"],
    ["intracerebral hemorrhage", "intracerebral haemorrhage", "ICH"],
    ["chronic subdural hematoma", "chronic subdural haematoma", "CSDH", "cSDH"],
    ["subdural hematoma", "subdural haematoma", "SDH"],
    ["extradural hematoma", "epidural hematoma", "extradural haematoma", "epidural haematoma", "EDH"],
    ["arteriovenous malformation", "AVM"],
    ["dural arteriovenous fistula", "DAVF", "dAVF"],
    ["cerebrospinal fluid", "CSF"],
    ["intracranial pressure", "ICP"],
    ["cerebral perfusion pressure", "CPP"],
    ["glasgow coma scale", "GCS"],
    ["glioblastoma", "glioblastoma multiforme", "GBM"],
    ["low grade glioma", "low-grade glioma", "LGG"],
    ["deep brain stimulation", "DBS"],
    ["spinal cord stimulation", "SCS"],
    ["anterior cervical discectomy and fusion", "ACDF"],
    ["transforaminal lumbar interbody fusion", "TLIF"],
    ["posterior lumbar interbody fusion", "PLIF"],
    ["external ventricular drain", "external ventricular drainage", "EVD"],
    ["ventriculoperitoneal shunt", "VP shunt", "VPS"],
    ["endoscopic third ventriculostomy", "ETV"],
    ["normal pressure hydrocephalus", "NPH", "iNPH"],
    ["idiopathic intracranial hypertension", "pseudotumor cerebri", "IIH"],
    ["traumatic brain injury", "TBI"],
    ["spinal cord injury", "SCI"],
    ["stereotactic radiosurgery", "SRS", "radiosurgery"],
    ["gamma knife", "GKRS"],
    ["trigeminal neuralgia", "tic douloureux", "TN"],
    ["microvascular decompression", "MVD"],
    ["posterior inferior cerebellar artery", "PICA"],
    ["anterior inferior cerebellar artery", "AICA"],
    ["superior cerebellar artery", "SCA"],
    ["middle cerebral artery", "MCA"],
    ["anterior cerebral artery", "ACA"],
    ["anterior communicating artery", "ACoA", "AComA", "AcomA"],
    ["posterior communicating artery", "PCoA", "PComA", "PcomA"],
    ["internal carotid artery", "ICA"],
    ["vertebral artery", "VA"],
    ["basilar artery", "BA"],
    ["superior sagittal sinus", "SSS"],
    ["endoscopic endonasal approach", "endoscopic endonasal", "EEA", "EEEA"],
    ["retrosigmoid", "retromastoid", "suboccipital retrosigmoid"],
    ["translabyrinthine", "translab"],
    ["far lateral", "far-lateral", "extreme lateral"],
    ["supracerebellar infratentorial", "SCIT"],
    ["orbitozygomatic", "OZ"],
    ["pterional", "frontotemporal"],
    ["intraoperative neurophysiological monitoring", "intraoperative neuromonitoring", "IONM"],
    ["motor evoked potentials", "MEP", "MEPs"],
    ["somatosensory evoked potentials", "SSEP", "SSEPs", "SEP"],
    ["brainstem auditory evoked potentials", "BAEP", "BAER", "ABR"],
    ["facial nerve", "CN VII", "seventh cranial nerve"],
    ["vestibulocochlear nerve", "CN VIII", "cochlear nerve"],
    ["trigeminal nerve", "CN V"],
    ["oculomotor nerve", "CN III"],
    ["abducens nerve", "abducent nerve", "CN VI"],
    ["house-brackmann", "house brackmann", "HB grade"],
    ["world federation of neurosurgical societies", "WFNS"],
    ["modified rankin scale", "mRS"],
    ["karnofsky performance status", "KPS"],
    ["extent of resection", "EOR"],
    ["gross total resection", "GTR"],
    ["subtotal resection", "STR"],
    ["magnetic resonance imaging", "MRI", "MR imaging"],
    ["computed tomography", "CT"],
    ["digital subtraction angiography", "DSA"],
    ["cerebral vasospasm", "vasospasm"],
    ["delayed cerebral ischemia", "delayed cerebral ischaemia", "DCI"],
    ["hemorrhage", "haemorrhage"],
    ["hematoma", "haematoma"],
    ["tumor", "tumour"],
    ["edema", "oedema"],
    ["ischemia", "ischaemia"],
]

_INDEX: dict[str, list[str]] = {}
for g in GROUPS:
    for term in g:
        _INDEX.setdefault(term.lower(), [])
        for t in g:
            if t not in _INDEX[term.lower()]:
                _INDEX[term.lower()].append(t)


def expand(term: str) -> list[str]:
    """Equivalent forms. Very short abbreviations (VS, VA, CT, TN...) are only used when the user typed
    them; they are not added as expansions of a full term because they collide with ordinary tokens
    (e.g. 'vs.' = versus)."""
    variants = _INDEX.get(term.lower())
    if not variants:
        return [term]
    return [v for v in variants if v.lower() == term.lower() or len(v) > 2]


def phrases() -> list[str]:
    """Multi-word keys sorted longest first, for greedy phrase recognition in queries."""
    return sorted((k for k in _INDEX if " " in k or "-" in k), key=len, reverse=True)
