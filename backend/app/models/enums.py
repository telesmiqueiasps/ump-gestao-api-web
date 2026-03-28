import enum


class OrgType(str, enum.Enum):
    federation = "federation"
    local_ump = "local_ump"


class TransactionType(str, enum.Enum):
    outras_receitas = "outras_receitas"
    outras_despesas = "outras_despesas"
    aci_recebida = "aci_recebida"
    aci_enviada = "aci_enviada"


class BoardRole(str, enum.Enum):
    presidente              = "presidente"
    vice_presidente         = "vice_presidente"
    primeiro_secretario     = "1_secretario"
    segundo_secretario      = "2_secretario"
    tesoureiro              = "tesoureiro"
    secretario_executivo    = "secretario_executivo"
    secretario_presbiterial = "secretario_presbiterial"
    conselheiro             = "conselheiro"


class MemberType(str, enum.Enum):
    ativo = "ativo"
    cooperador = "cooperador"